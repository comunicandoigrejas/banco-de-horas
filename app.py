import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ISOSED - Banco de Horas", layout="centered")

# --- CONEXÃO COM GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE APOIO ---

def buscar_dados(aba):
    """Lê dados de uma aba específica da planilha."""
    return conn.read(worksheet=aba, ttl=0)

def salvar_lancamento(novo_registro):
    """Salva um novo lançamento na aba 'Lancamentos'."""
    df_atual = buscar_dados("Lancamentos")
    df_final = pd.concat([df_atual, novo_registro], ignore_index=True)
    conn.update(worksheet="Lancamentos", data=df_final)
    st.cache_data.clear()

def calcular_horas_positivas(data, entrada, saida, descontar_almoco):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    # Regra do Sábado (1.5x)
    if data.weekday() == 5: diff *= 1.5
    return max(0, diff)

def calcular_debito(data, inteira, entrada=None, saida=None, almoco=False):
    if inteira:
        # Segunda a Quinta (0-3) = 9h | Sexta (4) = 8h
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

# --- CARREGAMENTO DE DADOS DO USUÁRIO ---
df_lancamentos = buscar_dados("Lancamentos")
df_user = df_lancamentos[df_lancamentos['usuario'] == st.session_state.usuario]

total_creditos = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos - total_debitos

# --- INTERFACE PRINCIPAL ---
st.sidebar.title(f"Olá, {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Banco de Horas")

tab1, tab2, tab3 = st.tabs(["➕ Horas Positivas", "➖ Horas Negativas", "📊 Saldo e Extrato"])

# --- TAB 1: CRÉDITOS ---
with tab1:
    restante_c = 36 - total_creditos
    st.info(f"Limite de crédito restante: **{max(0, restante_c):.2f}h**")
    
    if restante_c <= 0:
        st.error("Você já atingiu o limite máximo de 36h de crédito.")
    else:
        with st.form("f_cred"):
            d = st.date_input("Data do Lançamento")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Horário de Chegada", value=time(8,0))
            sai = c2.time_input("Horário de Saída", value=time(17,0))
            alm = st.checkbox("Descontar Almoço?", value=True)
            if st.form_submit_button("Lançar"):
                h = calcular_horas_positivas(d, ent, sai, alm)
                if h > restante_c: h = restante_c
                
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(d), "tipo": "Crédito", "horas": h}])
                salvar_lancamento(novo)
                st.success(f"Crédito de {h:.2f}h salvo!")
                st.rerun()

# --- TAB 2: DÉBITOS ---
with tab2:
    restante_d = 36 - total_debitos
    st.info(f"Limite de débito restante: **{max(0, restante_d):.2f}h**")
    
    if restante_d <= 0:
        st.error("Você já atingiu o limite máximo de 36h de débito.")
    else:
        modo = st.radio("Tipo de Débito:", ["Dia Inteiro", "Parcial"])
        with st.form("f_deb"):
            d_n = st.date_input("Data da Folga/Atraso")
            h_calc_deb = 0
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                ent_n = c1.time_input("Início", value=time(8,0))
                sai_n = c2.time_input("Fim", value=time(12,0))
                alm_n = st.checkbox("Descontar Almoço?", value=False)
            
            if st.form_submit_button("Lançar Débito"):
                if modo == "Dia Inteiro":
                    h_calc_deb = calcular_debito(d_n, True)
                else:
                    h_calc_deb = calcular_debito(d_n, False, ent_n, sai_n, alm_n)
                
                if h_calc_deb > restante_d: h_calc_deb = restante_d
                
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(d_n), "tipo": "Débito", "horas": h_calc_deb}])
                salvar_lancamento(novo)
                st.success(f"Débito de {h_calc_deb:.2f}h salvo!")
                st.rerun()

# --- TAB 3: SALDO E EXTRATO ---
with tab3:
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Créditos", f"{total_creditos:.2f}h")
    c2.metric("Total Débitos", f"{total_debitos:.2f}h")
    c3.metric("Saldo do Banco", f"{saldo_atual:.2f}h")
    
    st.subheader("Extrato Detalhado")
    st.dataframe(df_user, use_container_width=True)
