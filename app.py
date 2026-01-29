import streamlit as st
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Controle de Banco de Horas - Limite 36h", layout="centered")

# --- FUNÇÕES DE CÁLCULO ---

def calcular_horas_positivas(data, entrada, saida, descontar_almoco):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    
    # Regra do Sábado (1.5x)
    if data.weekday() == 5: 
        diff *= 1.5
    return max(0, diff)

def calcular_debito_folga(data, inteira, entrada=None, saida=None, almoco=False):
    if inteira:
        # Segunda a Quinta (0-3) = 9h | Sexta (4) = 8h
        return 9.0 if data.weekday() <= 3 else 8.0
    else:
        t1 = datetime.combine(data, entrada)
        t2 = datetime.combine(data, saida)
        diff = (t2 - t1).total_seconds() / 3600
        if almoco: diff -= 1
        return max(0, diff)

# --- LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Login de Usuário")
    user = st.text_input("Usuário")
    pwd = st.text_input("Senha", type="password")
    if st.button("Entrar"):
        if user and pwd: # Simplificação: qualquer user/pass entra para teste
            st.session_state.logado = True
            st.session_state.usuario = user
            st.rerun()
    st.stop()

# --- BANCO DE DADOS (SIMULADO) ---
if 'df_banco' not in st.session_state:
    # Criando colunas para separar o que é crédito e o que é débito
    st.session_state.df_banco = pd.DataFrame(columns=["usuario", "data", "tipo", "horas"])

# Filtrar dados do usuário atual
df_user = st.session_state.df_banco[st.session_state.df_banco['usuario'] == st.session_state.usuario]

# Calcular Totais Acumulados (A REGRA DOS 36H)
total_creditos_cadastrados = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos_cadastrados = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos_cadastrados - total_debitos_cadastrados

# --- INTERFACE ---
st.title("Controle de Banco de Horas")
st.sidebar.write(f"Usuário: **{st.session_state.usuario}**")

tab1, tab2, tab3 = st.tabs(["➕ Lançar Crédito", "➖ Lançar Débito", "📊 Saldo e Extrato"])

# ABA 1: CRÉDITOS
with tab1:
    st.subheader("Lançamento de Horas Extras")
    restante_credito = 36 - total_creditos_cadastrados
    st.info(f"Você ainda pode lançar: **{max(0, restante_credito):.2f}h** de crédito no total.")

    if restante_credito <= 0:
        st.error("Limite máximo de 36h de crédito atingido. Não é possível realizar mais horas para o banco.")
    else:
        with st.form("f_pos"):
            data = st.date_input("Data")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0))
            sai = c2.time_input("Saída", value=time(17,0))
            alm = st.checkbox("Descontar Almoço?", value=True)
            
            if st.form_submit_button("Registrar Crédito"):
                h = calcular_horas_positivas(data, ent, sai, alm)
                
                if h > restante_credito:
                    st.warning(f"Lançamento ajustado de {h:.2f}h para {restante_credito:.2f}h para respeitar o limite de 36h.")
                    h = restante_credito
                
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": data, "tipo": "Crédito", "horas": h}])
                st.session_state.df_banco = pd.concat([st.session_state.df_banco, novo], ignore_index=True)
                st.success(f"Crédito de {h:.2f}h registrado!")
                st.rerun()

# ABA 2: DÉBITOS
with tab2:
    st.subheader("Lançamento de Folgas/Atrasos")
    restante_debito = 36 - total_debitos_cadastrados
    st.info(f"Você ainda pode debitar: **{max(0, restante_debito):.2f}h** no total.")

    if restante_debito <= 0:
        st.error("Limite máximo de 36h de débito atingido.")
    else:
        modo = st.radio("Tipo:", ["Folga Inteira", "Parcial"])
        with st.form("f_neg"):
            data_n = st.date_input("Data do Débito")
            h_deb = 0
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                ent_n = c1.time_input("Início", value=time(8,0))
                sai_n = c2.time_input("Fim", value=time(12,0))
                alm_n = st.checkbox("Descontar Almoço?", value=False)
            
            if st.form_submit_button("Registrar Débito"):
                if modo == "Folga Inteira":
                    h_deb = calcular_debito_folga(data_n, True)
                else:
                    h_deb = calcular_debito_folga(data_n, False, ent_n, sai_n, alm_n)
                
                if h_deb > restante_debito:
                    st.warning(f"Débito ajustado para {restante_debito:.2f}h para não ultrapassar o limite de 36h.")
                    h_deb = restante_debito
                
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": data_n, "tipo": "Débito", "horas": h_deb}])
                st.session_state.df_banco = pd.concat([st.session_state.df_banco, novo], ignore_index=True)
                st.success(f"Débito de {h_deb:.2f}h registrado!")
                st.rerun()

# ABA 3: SALDO E EXTRATO
with tab3:
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Créditos (Max 36h)", f"{total_creditos_cadastrados:.2f}h")
    col2.metric("Total Débitos (Max 36h)", f"{total_debitos_cadastrados:.2f}h")
    col3.metric("Saldo Atual", f"{saldo_atual:.2f}h")
    
    st.divider()
    if st.button("Gerar Extrato"):
        st.dataframe(df_user, use_container_width=True)

if st.sidebar.button("Logoff"):
    st.session_state.logado = False
    st.rerun()
