import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ISOSED - Controle de Ponto", layout="centered")

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

def calcular_horas(data, entrada, saida, descontar_almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    
    # Regra do Sábado (1.5x) para horas positivas
    if tipo == "positivo" and data.weekday() == 5: 
        diff *= 1.5
    
    return max(0, diff)

# --- SISTEMA DE LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Login de Acesso")
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
df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario]

total_creditos = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos - total_debitos

# --- INTERFACE ---
st.sidebar.title(f"👤 {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Banco de Horas")

tab1, tab2, tab3 = st.tabs(["➕ Horas Positivas", "➖ Horas Negativas", "📊 Extrato e Saldo"])

# --- TAB 1: POSITIVAS ---
with tab1:
    restante_c = 36 - total_creditos
    st.info(f"Limite restante para crédito: **{max(0, restante_c):.2f}h**")
    
    if restante_c <= 0:
        st.error("Limite máximo de 36h de crédito atingido.")
    else:
        with st.form("f_cred"):
            d = st.date_input("Data do Trabalho Extra")
            st.write("Dica: Você pode digitar o horário manualmente no campo abaixo.")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0), step=300) # step 300 = 5 min
            sai = c2.time_input("Saída", value=time(17,0), step=300)
            alm = st.checkbox("Descontar 1h de Almoço?", value=True)
            
            if st.form_submit_button("Registrar"):
                h = calcular_horas(d, ent, sai, alm, "positivo")
                if h > restante_c: h = restante_c
                
                novo = pd.DataFrame([{
                    "usuario": st.session_state.usuario, 
                    "data": d.strftime("%d/%m/%Y"), 
                    "entrada": ent.strftime("%H:%M"), 
                    "saida": sai.strftime("%H:%M"), 
                    "tipo": "Crédito", 
                    "horas": h
                }])
                salvar_dados_completos(pd.concat([df_todos, novo], ignore_index=True))
                st.success(f"Lançamento de {h:.2f}h realizado!")
                st.rerun()

# --- TAB 2: NEGATIVAS ---
with tab2:
    restante_d = 36 - total_debitos
    st.info(f"Limite restante para débito: **{max(0, restante_d):.2f}h**")
    
    if restante_d <= 0:
        st.error("Limite máximo de 36h de débito atingido.")
    else:
        modo = st.radio("Tipo de falta/atraso:", ["Dia Inteiro", "Parcial"])
        with st.form("f_deb"):
            d_n = st.date_input("Data da Folga")
            h_calc_deb = 0
            ent_val, sai_val = "-", "-"
            
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                ent_n = c1.time_input("Início", value=time(8,0), step=300)
                sai_n = c2.time_input("Fim", value=time(12,0), step=300)
                alm_n = st.checkbox("Descontar Almoço?", value=False)
                ent_val = ent_n.strftime("%H:%M")
                sai_val = sai_n.strftime("%H:%M")
            
            if st.form_submit_button("Registrar Débito"):
                if modo == "Dia Inteiro":
                    # Regra: Seg-Qui = 9h | Sex = 8h
                    h_calc_deb = 9.0 if d_n.weekday() <= 3 else 8.0
                    ent_val, sai_val = "Folga", "Integral"
                else:
                    h_calc_deb = calcular_horas(d_n, ent_n, sai_n, alm_n, "negativo")
                
                if h_calc_deb > restante_d: h_calc_deb = restante_d
                
                novo = pd.DataFrame([{
                    "usuario": st.session_state.usuario, 
                    "data": d_n.strftime("%d/%m/%Y"), 
                    "entrada": ent_val, 
                    "saida": sai_val, 
                    "tipo": "Débito", 
                    "horas": h_calc_deb
                }])
                salvar_dados_completos(pd.concat([df_todos, novo], ignore_index=True))
                st.success("Débito registrado!")
                st.rerun()

# --- TAB 3: SALDO E EXTRATO ---
with tab3:
    c1, c2, c3 = st.columns(3)
    c1.metric("Créditos Realizados", f"{total_creditos:.2f}h")
    c2.metric("Débitos Realizados", f"{total_debitos:.2f}h")
    c3.metric("Saldo do Banco", f"{saldo_atual:.2f}h")
    
    st.divider()
    st.subheader("Conferência de Lançamentos")
    
    if not df_user.empty:
        # Reordenando e exibindo colunas para conferência
        cols_exibicao = ["data", "entrada", "saida", "tipo", "horas"]
        st.dataframe(df_user[cols_exibicao], use_container_width=True)
        
        st.divider()
        st.subheader("🗑️ Apagar Lançamento")
        opcoes_delete = {
            f"{row['data']} | {row['entrada']}-{row['saida']} | {row['tipo']} | {row['horas']:.2f}h": idx 
            for idx, row in df_user.iterrows()
        }
        selecionado = st.selectbox("Selecione o registro para apagar:", options=list(opcoes_delete.keys()))
        
        if st.button("Apagar Permanentemente", type="primary"):
            df_final = df_todos.drop(opcoes_delete[selecionado])
            salvar_dados_completos(df_final)
            st.success("Registro removido!")
            st.rerun()
    else:
        st.info("Nenhum lançamento registrado até o momento.")
