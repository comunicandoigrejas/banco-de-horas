import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA E CSS ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")

# CSS para esconder o header do Streamlit e limpar a tela
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
        # Garante que as horas sejam números decimais (corrige vírgula por ponto)
        df['horas'] = df['horas'].astype(str).str.replace(',', '.')
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0.0)
        # Limpa o texto do tipo para busca
        df['tipo_limpo'] = df['tipo'].astype(str).str.strip().str.lower()
        df['tipo_limpo'] = df['tipo_limpo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    return df

def salvar_dados(aba, df_novo):
    # Remove colunas de cálculo interno antes de salvar no Google Sheets
    cols_drop = ['tipo_limpo', 'data_dt', 'h_banco', 'h_pago', 'cota_progresso']
    df_save = df_novo.drop(columns=[c for c in cols_drop if c in df_novo.columns])
    conn.update(worksheet=aba, data=df_save)
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

# --- LOGIN ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'aba_ativa' not in st.session_state: st.session_state.aba_ativa = "Lançar Horas"

if not st.session_state.logado:
    st.title("🔐 Login ISOSED")
    with st.form("login"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            user_data = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not user_data.empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = user_data.iloc[0]['nome_exibicao']
                st.session_state.v_hora = float(user_data.iloc[0].get('valor_hora', 25.0))
                st.rerun()
            else: st.error("Erro no login.")
    st.stop()

# --- HEADER CENTRAL ---
st.markdown(f"### 👤 Usuário: **{st.session_state.nome}**")
if st.button("Sair do Sistema"):
    st.session_state.logado = False
    st.rerun()

st.title("Banco de Horas e Extras")

# --- NAVEGAÇÃO ---
c_nav1, c_nav2, c_nav3, c_nav4 = st.columns(4)
if c_nav1.button("➕ Créditos"): st.session_state.aba_ativa = "Lançar Horas"
if c_nav2.button("➖ Folgas"): st.session_state.aba_ativa = "Lançar Folgas"
if c_nav3.button("💰 Financeiro"): st.session_state.aba_ativa = "Financeiro"
if c_nav4.button("⚙️ Configurações"): st.session_state.aba_ativa = "Configurações"

st.divider()

# --- LÓGICA DE CÁLCULO CRONOLÓGICO ---
df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

saldo_folgas, extras_pagas, cota_total_acumulada = 0.0, 0.0, 0.0
historico_calculado = []

if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.dropna(subset=['data_dt']).sort_values('data_dt')
    
    for _, row in df_user.iterrows():
        h = float(row['horas'])
        h_banco, h_pago = 0.0, 0.0
        
        if row['tipo_limpo'] == "credito":
            # Verifica quanto ainda cabe na cota de 36h
            if cota_total_acumulada < 36:
                vaga = 36 - cota_total_acumulada
                h_banco = min(h, vaga)
                h_pago = max(0, h - vaga)
                
                saldo_folgas += h_banco
                extras_pagas += h_pago
                cota_total_acumulada += h
            else:
                h_pago = h
                extras_pagas += h_pago
        elif row['tipo_limpo'] == "debito":
            saldo_folgas -= h
            h_banco = -h
            
        historico_calculado.append({
            "Data": row['data'], 
            "Tipo": row['tipo'], 
            "Horas": h, 
            "No Banco": h_banco, 
            "Em Dinheiro": h_pago
        })

# --- TELAS ---

if st.session_state.aba_ativa == "Lançar Horas":
    st.info(f"Cota de Banco: **{min(36.0, cota_total_acumulada):.2f} / 36.00h**")
    st.progress(min(1.0, cota_total_acumulada / 36))
    with st.form("f_cred"):
        d = st.date_input("Data do Trabalho")
        col1, col2 = st.columns(2)
        ent, sai = col1.time_input("Entrada", value=time(8,0)), col2.time_input("Saída", value=time(17,0))
        alm = st.checkbox("Descontar Almoço (1h)?", value=True)
        if st.form_submit_button("Registrar"):
            # Cálculo de horas com multiplicadores
            delta = (datetime.combine(d, sai) - datetime.combine(d, ent)).total_seconds() / 3600
            if alm: delta -= 1
            mult = 1.5 if d.weekday() == 5 else 1.25
            # AQUI ESTÁ A TRAVA DE 2H (VERIFIQUE SE É ISSO QUE ESTÁ TE TRAVANDO EM 24)
            h_final = min(delta * mult, 2.0) if d.weekday() <= 4 else delta * mult
            
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h_final}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Lançar Folgas":
    st.write(f"Saldo para Folgas: **{saldo_folgas:.2f}h**")
    modo = st.radio("Duração:", ["Dia Inteiro", "Parcial"])
    with st.form("f_deb"):
        dn = st.date_input("Data da Folga")
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en, sn = c1.time_input("Início", value=time(8,0)), c2.time_input("Fim", value=time(12,0))
            alm_f = st.checkbox("Descontar Almoço?")
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro": h_f = 9.0 if dn.weekday() <= 3 else 8.0
            else: 
                h_f = (datetime.combine(dn, sn) - datetime.combine(dn, en)).total_seconds() / 3600
                if alm_f: h_f -= 1
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": dn.strftime("%d/%m/%Y"), 
                                  "entrada": "Folga", "saida": modo, "tipo": "Débito", "horas": h_f}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Financeiro":
    st.subheader("💰 Resumo e Auditoria")
    # Cálculos Financeiros
    salario_base = st.session_state.v_hora * 220
    bruto_extras = extras_pagas * (st.session_state.v_hora * 2.1)
    imp_b = calcular_impostos(salario_base)
    imp_t = calcular_impostos(salario_base + bruto_extras)
    liq_extras = bruto_extras - (imp_t - imp_b)

    c1, c2, c3 = st.columns(3)
    c1.metric("Saldo Banco", f"{saldo_folgas:.2f}h")
    c2.metric("Horas em R$", f"{extras_pagas:.2f}h")
    c3.metric("Líquido Extras", f"R$ {liq_extras:,.2f}")

    st.divider()
    st.write("🔍 **Auditoria de Cálculos (Como chegamos aos valores acima):**")
    st.table(pd.DataFrame(historico_calculado))
    
    if st.button("🚨 ZERAR CICLO", type="primary"):
        salvar_dados("Lancamentos", df_todos[df_todos['usuario'] != st.session_state.usuario])
        st.rerun()

elif st.session_state.aba_ativa == "Configurações":
    st.subheader("Configurações do Perfil")
    with st.form("f_config"):
        v_h = st.number_input("Valor da sua Hora (R$)", value=st.session_state.v_hora)
        if st.form_submit_button("Salvar Valor da Hora"):
            df_u = buscar_dados("Usuarios")
            df_u.loc[df_u['usuario'] == st.session_state.usuario, 'valor_hora'] = v_h
            salvar_dados("Usuarios", df_u)
            st.session_state.v_hora = v_h
            st.success("Valor atualizado!")
