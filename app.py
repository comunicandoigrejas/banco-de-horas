import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Sistema de Banco de Horas", layout="centered")

# --- CONEXÃO COM GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE APOIO ---

def buscar_dados(aba):
    """Lê dados de uma aba específica da planilha."""
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados_completos(df_novo):
    """Sobrescreve a aba 'Lancamentos' com o DataFrame atualizado."""
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_positivas(data, entrada, saida, descontar_almoco):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    if data.weekday() == 5: diff *= 1.5
    return max(0, diff)

def calcular_debito(data, inteira, entrada=None, saida=None, almoco=False):
    if inteira:
        return 9.0 if data.weekday() <= 3 else 8.0
    else:
        t1 = datetime.combine(data, entrada)
        t2 = datetime.combine(data, saida)
        diff = (t2 - t1).total_seconds() / 3600
        if almoco: diff -= 1
        return max(0, diff)

# --- SISTEMA DE LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Acesso ao Sistema")
    with st.form("login_form"):
        u_input = st.text_input("Usuário").lower().strip()
        p_input = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            valid = df_u[(df_u['usuario'] == u_input) & (df_u['senha'].astype(str) == p_input)]
            if not valid.empty:
                st.session_state.logado = True
                st.session_state.usuario = u_input
                st.session_state.nome = valid.iloc[0]['nome_exibicao']
                st.rerun()
            else:
                st.error("Usuário ou senha inválidos.")
    st.stop()

# --- CARREGAMENTO DE DADOS ---
df_todos_lancamentos = buscar_dados("Lancamentos")
df_user = df_todos_lancamentos[df_todos_lancamentos['usuario'] == st.session_state.usuario]

total_creditos = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos - total_debitos

# --- INTERFACE PRINCIPAL ---
st.sidebar.title(f"👤 {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Banco de Horas")

tab1, tab2, tab3 = st.tabs(["➕ Horas Positivas", "➖ Horas Negativas", "📊 Saldo e Extrato"])

# --- TAB 1: CRÉDITOS ---
with tab1:
    restante_c = 36 - total_creditos
    st.info(f"Limite de crédito disponível: **{max(0, restante_c):.2f}h**")
    
    if restante_c <= 0:
        st.error("Limite máximo de 36h de crédito atingido.")
    else:
        with st.form("f_cred"):
            d = st.date_input("Data")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0))
            sai = c2.time_input("Saída", value=time(17,0))
            alm = st.checkbox("Descontar Almoço?", value=True)
            if st.form_submit_button("Registrar Crédito"):
                h = calcular_horas_positivas(d, ent, sai, alm)
                if h > restante_c: h = restante_c
                
                novo_reg = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(d), "tipo": "Crédito", "horas": h}])
                salvar_dados_completos(pd.concat([df_todos_lancamentos, novo_reg], ignore_index=True))
                st.success("Lançamento realizado!")
                st.rerun()

# --- TAB 2: DÉBITOS ---
with tab2:
    restante_d = 36 - total_debitos
    st.info(f"Limite de débito disponível: **{max(0, restante_d):.2f}h**")
    
    if restante_d <= 0:
        st.error("Limite máximo de 36h de débito atingido.")
    else:
        modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
        with st.form("f_deb"):
            d_n = st.date_input("Data do Débito")
            h_calc_deb = 0
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                ent_n = c1.time_input("Início", value=time(8,0))
                sai_n = c2.time_input("Fim", value=time(12,0))
                alm_n = st.checkbox("Descontar Almoço?", value=False)
            
            if st.form_submit_button("Registrar Débito"):
                if modo == "Dia Inteiro":
                    h_calc_deb = calcular_debito(d_n, True)
                else:
                    h_calc_deb = calcular_debito(d_n, False, ent_n, sai_n, alm_n)
                
                if h_calc_deb > restante_d: h_calc_deb = restante_d
                
                novo_reg = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(d_n), "tipo": "Débito", "horas": h_calc_deb}])
                salvar_dados_completos(pd.concat([df_todos_lancamentos, novo_reg], ignore_index=True))
                st.success("Débito registrado!")
                st.rerun()

# --- TAB 3: SALDO E EXCLUSÃO ---
with tab3:
    col1, col2, col3 = st.columns(3)
    col1.metric("Créditos", f"{total_creditos:.2f}h")
    col2.metric("Débitos", f"{total_debitos:.2f}h")
    col3.metric("Saldo Atual", f"{saldo_atual:.2f}h")
    
    st.divider()
    st.subheader("Histórico de Lançamentos")
    
    if not df_user.empty:
        # Exibe a tabela para o usuário conferir
        st.dataframe(df_user, use_container_width=True)
        
        st.divider()
        st.subheader("🗑️ Apagar Lançamento Incorreto")
        
        # Criamos um dicionário para o selectbox: "Descrição visual" -> "Índice original no DataFrame"
        # Isso garante que apagaremos a linha correta na planilha global
        dict_opcoes = {
            f"{row['data']} | {row['tipo']} | {row['horas']:.2f}h": idx 
            for idx, row in df_user.iterrows()
        }
        
        selecionado = st.selectbox(
            "Selecione o registro que deseja excluir:", 
            options=list(dict_opcoes.keys()),
            help="Escolha o lançamento e clique no botão abaixo para apagar permanentemente."
        )
        
        if st.button("Confirmar Exclusão", type="primary"):
            indice_para_deletar = dict_opcoes[selecionado]
            
            # Removemos a linha do DataFrame global usando o índice
            df_atualizado = df_todos_lancamentos.drop(indice_para_deletar)
            
            # Salvamos a planilha inteira novamente sem aquela linha
            salvar_dados_completos(df_atualizado)
            
            st.success("Registro apagado com sucesso!")
            st.rerun()
    else:
        st.info("Você ainda não possui lançamentos registrados.")
