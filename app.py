import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA E INTERFACE ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")

# CSS para ocultar menus do Streamlit e GitHub
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

# --- FUNÇÕES NATIVAS DE DADOS ---

def buscar_dados(aba):
    # ttl=0 força a leitura em tempo real sem usar memória antiga
    df = conn.read(worksheet=aba, ttl=0)
    if aba == "Lancamentos":
        # Padroniza horas e tipos para evitar erros de soma
        df['horas'] = df['horas'].astype(str).str.replace(',', '.')
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0.0)
        df['tipo_limpo'] = df['tipo'].astype(str).str.strip().str.lower()
        df['tipo_limpo'] = df['tipo_limpo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    return df

def salvar_dados(aba, df_novo):
    # Prepara o dataframe removendo colunas de cálculos internos
    df_save = df_novo.copy()
    if aba == "Lancamentos":
        cols_drop = ['tipo_limpo', 'data_dt', 'h_banco', 'h_pago', 'cota_acum']
        df_save = df_save.drop(columns=[c for c in cols_drop if c in df_save.columns])
    
    # Atualiza a planilha e limpa todo o cache para refletir a mudança imediata
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

# --- SISTEMA DE LOGIN E ESTADO ---
if 'logado' not in st.session_state: st.session_state.logado = False
if 'aba_ativa' not in st.session_state: st.session_state.aba_ativa = "Créditos"

if not st.session_state.logado:
    st.title("🔐 Login")
    with st.form("login"):
        u, p = st.text_input("Usuário").lower().strip(), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            user_valid = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not user_valid.empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = user_valid.iloc[0]['nome_exibicao']
                st.session_state.v_hora = float(user_valid.iloc[0].get('valor_hora', 25.0))
                st.rerun()
            else: st.error("Acesso Negado")
    st.stop()

# --- HEADER ---
c_h1, c_h2 = st.columns([4, 1])
c_h1.subheader(f"👤 {st.session_state.nome}")
if c_h2.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Banco de Horas e Extras")

# --- NAVEGAÇÃO PERSISTENTE ---
c_nav1, c_nav2, c_nav3, c_nav4 = st.columns(4)
if c_nav1.button("➕ Créditos"): st.session_state.aba_ativa = "Créditos"
if c_nav2.button("➖ Folgas"): st.session_state.aba_ativa = "Folgas"
if c_nav3.button("💰 Financeiro"): st.session_state.aba_ativa = "Financeiro"
if c_nav4.button("⚙️ Configurações"): st.session_state.aba_ativa = "Configurações"
st.divider()

# --- PROCESSAMENTO LOGICO (36H E TRANSBORDO) ---
df_todos = buscar_dados("Lancamentos")
# Filtramos mantendo o Index original para a edição funcionar
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

saldo_folgas, total_h_pagas, cota_vida = 0.0, 0.0, 0.0

if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.dropna(subset=['data_dt']).sort_values('data_dt')
    
    for idx, row in df_user.iterrows():
        h = float(row['horas'])
        if row['tipo_limpo'] == "credito":
            if cota_vida < 36:
                vaga = 36 - cota_vida
                h_b = min(h, vaga)
                saldo_folgas += h_b
                total_h_pagas += max(0, h - vaga)
                cota_vida += h
            else:
                total_h_pagas += h
        elif row['tipo_limpo'] == "debito":
            saldo_folgas -= h

# --- TELAS ---

if st.session_state.aba_ativa == "Créditos":
    st.write(f"Cota Utilizada: **{min(36.0, cota_vida):.2f} / 36.00h**")
    st.progress(min(1.0, cota_vida / 36))
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent, sai = c1.time_input("Entrada", value=time(8,0)), c2.time_input("Saída", value=time(17,0))
        alm = st.checkbox("Descontar Almoço (1h)?", value=True)
        if st.form_submit_button("Lançar Crédito"):
            delta = (datetime.combine(d, sai) - datetime.combine(d, ent)).total_seconds() / 3600
            if alm: delta -= 1
            mult = 1.5 if d.weekday() == 5 else 1.25
            # Regra de limite 2h em dias úteis
            h_calc = min(delta * mult, 2.0) if d.weekday() <= 4 else delta * mult
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h_calc}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Folgas":
    st.write(f"Saldo disponível para folga: **{saldo_folgas:.2f}h**")
    modo = st.radio("Duração:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        dn = st.date_input("Data da Folga")
        hf, ev, sv = 0.0, "-", "-"
        alm_f = False
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en, sn = c1.time_input("Início", value=time(8,0)), c2.time_input("Fim", value=time(12,0))
            alm_f = st.checkbox("Descontar Almoço na Folga?")
            ev, sv = en.strftime("%H:%M"), sn.strftime("%H:%M")
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro": hf = 9.0 if dn.weekday() <= 3 else 8.0
            else: 
                hf = (datetime.combine(dn, sn) - datetime.combine(dn, en)).total_seconds() / 3600
                if alm_f: hf -= 1
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": dn.strftime("%d/%m/%Y"), 
                                  "entrada": ev, "saida": sv, "tipo": "Débito", "horas": float(hf)}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Financeiro":
    salario_base = st.session_state.v_hora * 220
    bruto_extras = total_h_pagas * (st.session_state.v_hora * 2.1)
    imp_b = calcular_impostos(salario_base)
    imp_t = calcular_impostos(salario_base + bruto_extras)
    liq_ex = bruto_extras - (imp_t - imp_b)

    c1, c2, c3 = st.columns(3)
    c1.metric("Saldo Folgas", f"{saldo_folgas:.2f}h")
    c2.metric("Horas em R$", f"{total_h_pagas:.2f}h")
    c3.metric("Líquido Extras", f"R$ {liq_ex:,.2f}")

    st.divider()
    if not df_user.empty:
        st.subheader("Extrato")
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        # --- FUNÇÃO EDITAR (Sincronizada com o Index Real) ---
        with st.expander("📝 Editar Lançamento"):
            ops = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
            item_sel = st.selectbox("Selecione o registro para alterar:", options=list(ops.keys()))
            idx_real = ops[item_sel]
            
            with st.form("f_edit"):
                ed_d = st.text_input("Data", value=df_todos.at[idx_real, 'data'])
                c1, c2 = st.columns(2)
                ed_e, ed_s = c1.text_input("Entrada", value=df_todos.at[idx_real, 'entrada']), c2.text_input("Saída", value=df_todos.at[idx_real, 'saida'])
                ed_h = st.number_input("Horas", value=float(df_todos.at[idx_real, 'horas']))
                if st.form_submit_button("Salvar Alteração"):
                    df_todos.at[idx_real, 'data'] = ed_d
                    df_todos.at[idx_real, 'entrada'] = ed_e
                    df_todos.at[idx_real, 'saida'] = ed_s
                    df_todos.at[idx_real, 'horas'] = ed_h
                    salvar_dados("Lancamentos", df_todos)
                    st.success("Alterado!")
                    st.rerun()

        st.divider()
        # --- ZERAR (Sincronizado e com Limpeza de Cache) ---
        if st.button("🚨 ZERAR TODO O CICLO", type="primary"):
            df_final = df_todos[df_todos['usuario'] != st.session_state.usuario]
            salvar_dados("Lancamentos", df_final)
            st.success("Ciclo zerado!")
            st.rerun()

elif st.session_state.aba_ativa == "Configurações":
    st.subheader("⚙️ Configurações")
    with st.form("f_v"):
        v_nov = st.number_input("Valor da sua Hora (R$)", value=st.session_state.v_hora)
        if st.form_submit_button("Salvar Valor"):
            df_u = buscar_dados("Usuarios")
            df_u.loc[df_u['usuario'] == st.session_state.usuario, 'valor_hora'] = v_nov
            salvar_dados("Usuarios", df_u)
            st.session_state.v_hora = v_nov
            st.success("Valor atualizado!")

    st.divider()
    with st.expander("🔐 Trocar Senha"):
        with st.form("f_p"):
            pa, pn = st.text_input("Senha Atual", type="password"), st.text_input("Nova Senha", type="password")
            if st.form_submit_button("Atualizar"):
                df_u = buscar_dados("Usuarios")
                idx_u = df_u[df_u['usuario'] == st.session_state.usuario].index
                if str(df_u.loc[idx_u, 'senha'].values[0]) == pa:
                    df_u.loc[idx_u, 'senha'] = pn
                    salvar_dados("Usuarios", df_u)
                    st.success("Senha trocada!")
                else: st.error("Senha atual incorreta.")
