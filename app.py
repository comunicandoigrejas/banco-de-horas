import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ISOSED - Banco de Horas", layout="centered")

# --- CONEXÃO COM GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE APOIO E REGRAS DE NEGÓCIO ---

def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados_completos(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_logic(data, entrada, saida, descontar_almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff_segundos = (t2 - t1).total_seconds()
    
    if descontar_almoco:
        diff_segundos -= 3600 # 1 hora
    
    horas_brutas = max(0, diff_segundos / 3600)
    
    if tipo == "positivo":
        # REGRA: Dias de semana (Segunda 0 a Sexta 4)
        if data.weekday() <= 4:
            # Limite de 2 horas diárias
            horas_validas = min(horas_brutas, 2.0)
            return horas_validas * 1.25
        # REGRA: Sábado (5)
        elif data.weekday() == 5:
            return horas_brutas * 1.5
    
    return horas_brutas # Para débitos parciais ou outros casos

# --- SISTEMA DE LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

if not st.session_state.logado:
    st.title("🔐 Acesso ISOSED")
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

tab1, tab2, tab3 = st.tabs(["➕ Créditos", "➖ Débitos", "📊 Extrato"])

# --- TAB 1: CRÉDITOS (COM NOVAS REGRAS) ---
with tab1:
    restante_c = 36 - total_creditos
    st.info(f"Limite total de créditos: **{max(0, restante_c):.2f}h**")
    
    if restante_c <= 0:
        st.error("Você já atingiu o teto máximo de 36 horas de crédito.")
    else:
        with st.form("f_cred"):
            d = st.date_input("Data da Extra")
            st.caption("Nota: Dias de semana limitados a 2h (1.25x). Sábados (1.5x).")
            c1, c2 = st.columns(2)
            ent = c1.time_input("Entrada", value=time(8,0), step=300)
            sai = c2.time_input("Saída", value=time(17,0), step=300)
            alm = st.checkbox("Descontar Almoço?", value=True)
            
            if st.form_submit_button("Registrar Crédito"):
                h_final = calcular_horas_logic(d, ent, sai, alm, "positivo")
                
                # Alerta sobre o limite de 2h na semana
                t1_check = datetime.combine(d, ent)
                t2_check = datetime.combine(d, sai)
                brutas = (t2_check - t1_check).total_seconds() / 3600
                if alm: brutas -= 1
                
                if d.weekday() <= 4 and brutas > 2:
                    st.warning("Trabalho em dia de semana limitado a 2h para o banco.")
                
                # Trava dos 36h
                if h_final > restante_c:
                    h_final = restante_c
                
                novo = pd.DataFrame([{
                    "usuario": st.session_state.usuario, 
                    "data": d.strftime("%d/%m/%Y"), 
                    "entrada": ent.strftime("%H:%M"), 
                    "saida": sai.strftime("%H:%M"), 
                    "tipo": "Crédito", 
                    "horas": h_final
                }])
                salvar_dados_completos(pd.concat([df_todos, novo], ignore_index=True))
                st.success(f"Registrado: {h_final:.2f}h")
                st.rerun()

# --- TAB 2: DÉBITOS ---
with tab2:
    restante_d = 36 - total_debitos
    st.info(f"Limite total de débitos: **{max(0, restante_d):.2f}h**")
    
    if restante_d <= 0:
        st.error("Você já atingiu o teto máximo de 36 horas de débito.")
    else:
        modo = st.radio("Tipo de débito:", ["Dia Inteiro", "Parcial"])
        with st.form("f_deb"):
            d_n = st.date_input("Data da Folga/Atraso")
            h_deb = 0
            e_val, s_val = "-", "-"
            
            if modo == "Parcial":
                c1, c2 = st.columns(2)
                ent_n = c1.time_input("Início", value=time(8,0), step=300)
                sai_n = c2.time_input("Fim", value=time(12,0), step=300)
                alm_n = st.checkbox("Descontar Almoço?", value=False)
                e_val, s_val = ent_n.strftime("%H:%M"), sai_n.strftime("%H:%M")
            
            if st.form_submit_button("Registrar Débito"):
                if modo == "Dia Inteiro":
                    h_deb = 9.0 if d_n.weekday() <= 3 else 8.0
                    e_val, s_val = "Folga", "Integral"
                else:
                    h_deb = calcular_horas_logic(d_n, ent_n, sai_n, alm_n, "negativo")
                
                if h_deb > restante_d: h_deb = restante_d
                
                novo = pd.DataFrame([{
                    "usuario": st.session_state.usuario, 
                    "data": d_n.strftime("%d/%m/%Y"), 
                    "entrada": e_val, "saida": s_val, 
                    "tipo": "Débito", "horas": h_deb
                }])
                salvar_dados_completos(pd.concat([df_todos, novo], ignore_index=True))
                st.success("Débito salvo!")
                st.rerun()

# --- TAB 3: EXTRATO ---
with tab3:
    c1, c2, c3 = st.columns(3)
    c1.metric("Acúmulo Créditos", f"{total_creditos:.2f}h")
    c2.metric("Acúmulo Débitos", f"{total_debitos:.2f}h")
    c3.metric("Saldo Atual", f"{saldo_atual:.2f}h")
    
    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        st.subheader("🗑️ Excluir Registro")
        opcoes = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
        sel = st.selectbox("Escolha o item:", options=list(opcoes.keys()))
        if st.button("Remover", type="primary"):
            df_final = df_todos.drop(opcoes[sel])
            salvar_dados_completos(df_final)
            st.rerun()
