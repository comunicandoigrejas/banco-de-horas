import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ISOSED - Banco de Horas", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE REGRAS ---

def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_final(data, entrada, saida, descontar_almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if descontar_almoco: diff -= 1
    
    brutas = max(0, diff)
    
    if tipo == "positivo":
        if data.weekday() <= 4: # Segunda a Sexta
            # Limite de 2h já com o acréscimo de 1.25
            calculado = brutas * 1.25
            return min(calculado, 2.0)
        elif data.weekday() == 5: # Sábado
            return brutas * 1.5
    
    return brutas # Para débitos parciais

# --- SISTEMA DE LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Acesso ao Sistema")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            valid = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not valid.empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = valid.iloc[0]['nome_exibicao']
                st.rerun()
            else: st.error("Acesso negado.")
    st.stop()

# --- DADOS E SALDO ---
df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario]
total_c = df_user[df_user['tipo'] == "Crédito"]['horas'].sum()
total_d = df_user[df_user['tipo'] == "Débito"]['horas'].sum()

# Cálculo do Saldo (Créditos Realizados - Débitos Realizados)
saldo_total = total_c - total_d

# --- INTERFACE ---
st.sidebar.write(f"👤 {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Banco de Horas")

tab1, tab2, tab3 = st.tabs(["➕ Créditos", "➖ Débitos", "📊 Extrato"])

with tab1:
    restante = 36 - total_c
    st.info(f"Limite para novos créditos: **{max(0, restante):.2f}h**")
    if restante <= 0: st.error("Limite de 36h de crédito atingido.")
    else:
        with st.form("f_c"):
            d = st.date_input("Data")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0), step=300)
            sai = c2.time_input("Saída", value=time(17,0), step=300)
            alm = st.checkbox("Descontar Almoço?", value=True)
            if st.form_submit_button("Registrar"):
                h = calcular_horas_final(d, ent, sai, alm, "positivo")
                if h > restante: h = restante
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                      "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                      "tipo": "Crédito", "horas": h}])
                salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
                st.success(f"Crédito de {h:.2f}h registrado!")
                st.rerun()

with tab2:
    restante_d = 36 - total_d
    st.info(f"Limite para novos débitos: **{max(0, restante_d):.2f}h**")
    if restante_d <= 0: st.error("Limite de 36h de débito atingido.")
    else:
        modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
        with st.form("f_d"):
            d_n = st.date_input("Data da Folga")
            h_deb, e_v, s_v = 0, "-", "-"
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                en_n = c1.time_input("Início", value=time(8,0), step=300)
                sa_n = c2.time_input("Fim", value=time(12,0), step=300)
                al_n = st.checkbox("Descontar Almoço?", value=False)
                e_v, s_v = en_n.strftime("%H:%M"), sa_n.strftime("%H:%M")
            if st.form_submit_button("Registrar Débito"):
                if modo == "Dia Inteiro":
                    h_deb = 9.0 if d_n.weekday() <= 3 else 8.0
                    e_v, s_v = "Folga", "Integral"
                else: h_deb = calcular_horas_final(d_n, en_n, sa_n, al_n, "negativo")
                if h_deb > restante_d: h_deb = restante_d
                novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                      "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": h_deb}])
                salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
                st.success("Débito registrado!")
                st.rerun()

with tab3:
    st.subheader("Resumo e Conferência")
    m1, m2, m3 = st.columns(3)
    m1.metric("Acúmulo Créditos", f"{total_c:.2f}h")
    m2.metric("Acúmulo Débitos", f"{total_d:.2f}h")
    
    # SALDO ATUAL: Mostra o valor negativo se houver dívida de horas
    m3.metric(
        label="Saldo Atual", 
        value=f"{saldo_total:.2f}h", 
        delta="Dívida de Horas" if saldo_total < 0 else "Crédito Disponível",
        delta_color="inverse" if saldo_total < 0 else "normal"
    )
    
    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        st.divider()
        st.subheader("🗑️ Apagar Registro")
        ops = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
        sel = st.selectbox("Selecione para remover:", options=list(ops.keys()))
        if st.button("Remover Permanentemente", type="primary"):
            salvar_dados(df_todos.drop(ops[sel]))
            st.rerun()
