import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd

# --- CONEXÃO ---
conn = st.connection("gsheets", type=GSheetsConnection)

def realizar_login():
    if 'logado' not in st.session_state:
        st.session_state.logado = False

    if not st.session_state.logado:
        st.title("🔐 Sistema de Ponto - Login")
        
        with st.form("login_form"):
            user_input = st.text_input("Usuário").lower().strip()
            pass_input = st.text_input("Senha", type="password")
            botao_entrar = st.form_submit_button("Acessar Sistema")

            if botao_entrar:
                # Busca a lista de usuários na aba "Usuarios"
                try:
                    df_usuarios = conn.read(worksheet="Usuarios", ttl=0)
                    
                    # Verifica se o usuário e senha batem
                    usuario_valido = df_usuarios[
                        (df_usuarios['usuario'] == user_input) & 
                        (df_usuarios['senha'].astype(str) == pass_input)
                    ]

                    if not usuario_valido.empty:
                        st.session_state.logado = True
                        st.session_state.usuario = user_input
                        st.session_state.nome_tela = usuario_valido.iloc[0]['nome_exibicao']
                        st.rerun()
                    else:
                        st.error("Usuário ou senha incorretos.")
                except Exception as e:
                    st.error("Erro ao conectar com a base de usuários.")
        
        st.stop() # Interrompe o script aqui se não estiver logado

# --- EXECUÇÃO DO LOGIN ---
realizar_login()

# --- ABAIXO DAQUI O CÓDIGO SÓ RODA SE O LOGIN FOR SUCESSO ---

st.sidebar.success(f"Conectado como: {st.session_state.nome_tela}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

# Restante da lógica de lançamentos e regra de 36h...
