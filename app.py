import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA E CSS ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")

# CSS para esconder o header (GitHub/Menu) e estilizar botões de navegação
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    footer {visibility: hidden;}
    .stAppDeployButton {display:none;}
    .stButton button {width: 100%;}
    </style>
    """, unsafe_allow_html=True)

conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE APOIO ---

def buscar_dados(aba):
    df = conn.read(worksheet=aba, ttl=0)
    if aba == "Lancamentos":
        df['horas'] = df['horas'].astype(str).str.replace(',', '.')
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0.0)
        df['tipo_limpo'] = df['tipo'].astype(str).str.strip().str.lower()
        df['tipo_limpo'] = df['tipo_limpo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    return df

def salvar_dados(aba, df_novo):
    if aba == "Lancamentos":
        cols_drop = ['tipo_limpo', 'data_dt', 'cota_acumulada', 'h_banco', 'h_pago']
        df_novo = df_novo.drop(columns=[c for c in cols_drop if c in df_novo.columns])
    conn.update(worksheet=aba, data=df_novo)
    st.cache_data.clear()

def calcular_impostos(valor_bruto):
    inss = 0
    faixas_inss = [(1518.0, 0.075), (2800.0, 0.09), (4200.0, 0.12), (8157.0, 0.14)]
    ant = 0
    for lim, aliq in faixas_inss:
        if valor_bruto > lim:
            inss += (lim - ant) * aliq
            ant = lim
        else:
            inss += (valor_bruto - ant) * aliq
            break
    base_ir = valor_bruto - inss
    ir = 0
    if base_ir > 4664.68: ir = (base_ir * 0.275) - 893.66
    elif base_ir > 3751.05: ir = (base_ir * 0.225) - 662.77
    elif base_ir > 2826.65: ir = (base_ir * 0.15) - 381.44
    elif base_ir > 2259.20: ir = (base_ir * 0.075) - 169.44
    return inss + max(0, ir)

# --- INICIALIZAÇÃO DE ESTADO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'aba_ativa' not in st.session_state: st.session_state.aba_ativa = "Créditos"

# --- LOGIN ---
if not st.session_state.logado:
    st.title("🔐 Acesso ao Sistema")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            user_data = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not user_data.empty:
                st.session_state.logado = True
                st.session_state.usuario = u
                st.session_state.nome = user_data.iloc[0]['nome_exibicao']
                # Carrega o valor da hora salvo na planilha (se houver a coluna)
                st.session_state.v_hora = float(user_data.iloc[0].get('valor_hora', 25.0))
                st.rerun()
            else: st.error("Acesso negado.")
    st.stop()

# --- HEADER ---
c_h1, c_h2 = st.columns([4, 1])
c_h1.subheader(f"👤 Usuário: {st.session_state.nome}")
if c_h2.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Banco de Horas e Extras")

# --- MENU DE NAVEGAÇÃO (SUBSTITUI ST.TABS PARA EVITAR RESET) ---
c_nav1, c_nav2, c_nav3, c_nav4 = st.columns(4)
if c_nav1.button("➕ Créditos"): st.session_state.aba_ativa = "Créditos"
if c_nav2.button("➖ Folgas"): st.session_state.aba_ativa = "Folgas"
if c_nav3.button("💰 Financeiro"): st.session_state.aba_ativa = "Financeiro"
if c_nav4.button("⚙️ Configurações"): st.session_state.aba_ativa = "Configurações"

st.divider()

# --- PROCESSAMENTO DE DADOS ---
df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

saldo_folgas, total_h_pagas, cota_vida = 0.0, 0.0, 0.0

if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.dropna(subset=['data_dt']).sort_values('data_dt')
    for _, row in df_user.iterrows():
        h = float(row['horas'])
        if row['tipo_limpo'] == "credito":
            if cota_vida < 36:
                vaga = 36 - cota_vida
                ao_banco = min(h, vaga)
                saldo_folgas += ao_banco
                total_h_pagas += max(0, h - vaga)
                cota_vida += h
            else: total_h_pagas += h
        elif row['tipo_limpo'] == "debito":
            saldo_folgas -= h

# --- TELAS ---

if st.session_state.aba_ativa == "Créditos":
    st.write(f"Cota Utilizada: **{min(36.0, cota_vida):.2f} / 36.00h**")
    st.progress(min(1.0, cota_vida / 36))
    with st.form("f_c"):
        d = st.date_input("Data")
        col1, col2 = st.columns(2)
        ent, sai = col1.time_input("Entrada", value=time(8,0)), col2.time_input("Saída", value=time(17,0))
        alm = st.checkbox("Descontar Almoço (1h)?", value=True)
        if st.form_submit_button("Registrar Crédito"):
            h_b = (datetime.combine(d, sai) - datetime.combine(d, ent)).total_seconds() / 3600
            if alm: h_b -= 1
            mult = 1.5 if d.weekday() == 5 else 1.25
            h_calc = min(h_b * mult, 2.0) if d.weekday() <= 4 else h_b * mult
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h_calc}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Folgas":
    st.write(f"Saldo para folgas: **{saldo_folgas:.2f}h**")
    modo = st.radio("Duração:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        dn = st.date_input("Data")
        hf, ev, sv = 0.0, "-", "-"
        alm_f = False
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en, sn = c1.time_input("Início", value=time(8,0)), c2.time_input("Fim", value=time(12,0))
            alm_f = st.checkbox("Descontar Almoço na Folga Parcial?")
            ev, sv = en.strftime("%H:%M"), sn.strftime("%H:%M")
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro":
                hf = 9.0 if dn.weekday() <= 3 else 8.0
                ev, sv = "Folga", "Integral"
            else:
                hf = (datetime.combine(dn, sn) - datetime.combine(dn, en)).total_seconds() / 3600
                if alm_f: hf -= 1
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": dn.strftime("%d/%m/%Y"), 
                                  "entrada": ev, "saida": sv, "tipo": "Débito", "horas": float(hf)}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Financeiro":
    st.subheader("Resumo Financeiro e Banco")
    salario_base = st.session_state.v_hora * 220
    bruto_ex = total_h_pagas * (st.session_state.v_hora * 2.1)
    imp_b = calcular_impostos(salario_base)
    imp_t = calcular_impostos(salario_base + bruto_ex)
    liq_ex = bruto_ex - (imp_t - imp_b)

    c1, c2, c3 = st.columns(3)
    c1.metric("Saldo de Horas", f"{saldo_folgas:.2f}h")
    c2.metric("Horas em R$", f"{total_h_pagas:.2f}h")
    c3.metric("Líquido Extra", f"R$ {liq_ex:,.2f}")

    st.divider()
    st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
    if st.button("🚨 ZERAR CICLO", type="primary"):
        salvar_dados("Lancamentos", df_todos[df_todos['usuario'] != st.session_state.usuario])
        st.rerun()

elif st.session_state.aba_ativa == "Configurações":
    st.subheader("Configurações do Perfil")
    
    with st.form("f_config"):
        v_h = st.number_input("Valor da sua Hora (R$):", min_value=0.0, value=st.session_state.v_hora)
        if st.form_submit_button("Salvar Valor da Hora"):
            df_u = buscar_dados("Usuarios")
            idx = df_u[df_u['usuario'] == st.session_state.usuario].index
            df_u.loc[idx, 'valor_hora'] = v_h
            salvar_dados("Usuarios", df_u)
            st.session_state.v_hora = v_h
            st.success("Valor atualizado!")
            st.rerun()
    
    st.divider()
    with st.expander("Alterar Senha"):
        with st.form("f_senha"):
            p_a = st.text_input("Senha Atual", type="password")
            p_n = st.text_input("Nova Senha", type="password")
            if st.form_submit_button("Atualizar Senha"):
                df_u = buscar_dados("Usuarios")
                idx = df_u[df_u['usuario'] == st.session_state.usuario].index
                if str(df_u.loc[idx, 'senha'].values[0]) == p_a:
                    df_u.loc[idx, 'senha'] = p_n
                    salvar_dados("Usuarios", df_u)
                    st.success("Senha alterada!")
                else: st.error("Senha incorreta.")
