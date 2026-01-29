import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA CONEXÃO ---
conn = st.connection("gsheets", type=GSheetsConnection)

def buscar_dados():
    # Busca os dados da aba "Lancamentos"
    return conn.read(worksheet="Lancamentos", ttl=0) # ttl=0 garante dados em tempo real

def salvar_dados(df_novo):
    df_atual = buscar_dados()
    # Combina os dados antigos com o novo lançamento
    df_final = pd.concat([df_atual, df_novo], ignore_index=True)
    conn.update(worksheet="Lancamentos", data=df_final)
    st.cache_data.clear() # Limpa o cache para atualizar a tela

# --- LÓGICA DE CÁLCULO (MANTIDA) ---
def calcular_horas_positivas(data, entrada, saida, descontar_almoco):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    if data.weekday() == 5: diff *= 1.5
    return max(0, diff)

def calcular_debito_folga(data, inteira):
    # Segunda a Quinta (0-3) = 9h | Sexta (4) = 8h
    return 9.0 if data.weekday() <= 3 else 8.0

# --- INTERFACE E LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Login Banco de Horas")
    user = st.text_input("Usuário")
    if st.button("Entrar"):
        st.session_state.logado = True
        st.session_state.usuario = user.lower()
        st.rerun()
    st.stop()

# --- PROCESSAMENTO DE DADOS DO GOOGLE SHEETS ---
df_total = buscar_dados()
# Filtrar apenas o usuário atual
df_user = df_total[df_total['usuario'] == st.session_state.usuario]

# Totais para a regra de 36h
total_creditos = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_debitos = df_user[df_user['tipo'] == "Débito"]['horas'].sum()
saldo_atual = total_creditos - total_debitos

# --- LAYOUT DO APP ---
st.title(f"Controle de {st.session_state.usuario.capitalize()}")
tab1, tab2, tab3 = st.tabs(["➕ Lançar Horas", "➖ Lançar Folga", "📊 Extrato Real"])

with tab1:
    restante_c = 36 - total_creditos
    if restante_c <= 0:
        st.error("Limite de 36h de crédito atingido.")
    else:
        with st.form("f_pos"):
            data = st.date_input("Data")
            c1, c2 = st.columns(2)
            ent, sai = c1.time_input("Entrada"), c2.time_input("Saída")
            alm = st.checkbox("Almoço", value=True)
            if st.form_submit_button("Registrar Crédito"):
                h = calcular_horas_positivas(data, ent, sai, alm)
                if h > restante_c: h = restante_c
                
                novo_df = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(data), "tipo": "Crédito", "horas": h}])
                salvar_dados(novo_df)
                st.success("Salvo no Google Sheets!")
                st.rerun()

with tab2:
    restante_d = 36 - total_debitos
    if restante_d <= 0:
        st.error("Limite de 36h de débito atingido.")
    else:
        with st.form("f_neg"):
            data_n = st.date_input("Data da Folga")
            if st.form_submit_button("Registrar Folga Integral"):
                h_deb = calcular_debito_folga(data_n, True)
                if h_deb > restante_d: h_deb = restante_d
                
                novo_df = pd.DataFrame([{"usuario": st.session_state.usuario, "data": str(data_n), "tipo": "Débito", "horas": h_deb}])
                salvar_dados(novo_df)
                st.success("Débito Registrado!")
                st.rerun()

with tab3:
    st.metric("Saldo Atual", f"{saldo_atual:.2f}h")
    st.write("### Histórico vindo da Planilha")
    st.dataframe(df_user, use_container_width=True)
