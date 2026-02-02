import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA E CSS ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")

# CSS para esconder o header do Streamlit (GitHub e Menu)
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
        # Padronização de dados
        df['horas'] = df['horas'].astype(str).str.replace(',', '.')
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0.0)
        df['tipo_limpo'] = df['tipo'].astype(str).str.strip().str.lower()
        df['tipo_limpo'] = df['tipo_limpo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    return df

def salvar_dados(aba, df_novo):
    # Limpeza de colunas de cálculo antes de subir
    df_save = df_novo.copy()
    if aba == "Lancamentos":
        cols_drop = ['tipo_limpo', 'data_dt', 'h_banco', 'h_pago', 'cota_acum']
        df_save = df_save.drop(columns=[c for c in cols_drop if c in df_save.columns])
    
    conn.update(worksheet=aba, data=df_save)
    st.cache_data.clear()
    st.cache_resource.clear()

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

# --- LOGIN E NAVEGAÇÃO ---
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

c_nav1, c_nav2, c_nav3, c_nav4 = st.columns(4)
if c_nav1.button("➕ Créditos"): st.session_state.aba_ativa = "Créditos"
if c_nav2.button("➖ Folgas"): st.session_state.aba_ativa = "Folgas"
if c_nav3.button("💰 Financeiro"): st.session_state.aba_ativa = "Financeiro"
if c_nav4.button("⚙️ Configurações"): st.session_state.aba_ativa = "Configurações"
st.divider()

# --- PROCESSAMENTO ---
df_todos = buscar_dados("Lancamentos")
# Guardamos o índice original para a edição funcionar
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
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent, sai = c1.time_input("Entrada", value=time(8,0)), c2.time_input("Saída", value=time(17,0))
        alm = st.checkbox("Descontar Almoço?", value=True)
        if st.form_submit_button("Lançar"):
            delta = (datetime.combine(d, sai) - datetime.combine(d, ent)).total_seconds() / 3600
            if alm: delta -= 1
            mult = 1.5 if d.weekday() == 5 else 1.25
            h_calc = min(delta * mult, 2.0) if d.weekday() <= 4 else delta * mult
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h_calc}])
            salvar_dados("Lancamentos", pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

elif st.session_state.aba_ativa == "Folgas":
    st.write(f"Saldo disponível: **{saldo_folgas:.2f}h**")
    modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        dn = st.date_input("Data")
        hf, ev, sv = 0.0, "-", "-"
        alm_f = False
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en, sn = c1.time_input("Início", value=time(8,0)), c2.time_input("Fim", value=time(12,0))
            alm_f = st.checkbox("Descontar Almoço?")
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

    col1, col2, col3 = st.columns(3)
    col1.metric("Saldo Folgas", f"{saldo_folgas:.2f}h")
    col2.metric("Horas em R$", f"{total_h_pagas:.2f}h")
    col3.metric("Líquido Extras", f"R$ {liq_ex:,.2f}")

    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        # --- EDITAR LANÇAMENTO (CORRIGIDO) ---
        with st.expander("📝 Editar um Lançamento"):
            # Criamos a lista de opções usando o índice original do df_todos
            ops_edit = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
            sel_edit = st.selectbox("Selecione o registro para alterar:", options=list(ops_edit.keys()))
            idx_real = ops_edit[sel_edit]
            
            with st.form("form_edicao"):
                ed_data = st.text_input("Data (DD/MM/AAAA)", value=df_todos.at[idx_real, 'data'])
                c1, c2 = st.columns(2)
                ed_ent = c1.text_input("Entrada", value=df_todos.at[idx_real, 'entrada'])
                ed_sai = c2.text_input("Saída", value=df_todos.at[idx_real, 'saida'])
                ed_horas = st.number_input("Horas Calculadas", value=float(df_todos.at[idx_real, 'horas']))
                if st.form_submit_button("Salvar Alterações"):
                    df_todos.at[idx_real, 'data'] = ed_data
                    df_todos.at[idx_real, 'entrada'] = ed_ent
                    df_todos.at[idx_real, 'saida'] = ed_sai
                    df_todos.at[idx_real, 'horas'] = ed_horas
                    salvar_dados("Lancamentos", df_todos)
                    st.success("Registro atualizado!")
                    st.rerun()

        st.divider()
        # --- ZERAR CICLO (CORRIGIDO) ---
        if st.button("🚨 ZERAR TODO O CICLO", type="primary"):
            # Mantém apenas as linhas que NÃO são do usuário logado
            df_final = df_todos[df_todos['usuario'] != st.session_state.usuario]
            salvar_dados("Lancamentos", df_final)
            st.success("Seu ciclo foi zerado com sucesso!")
            st.rerun()

elif st.session_state.aba_ativa == "Configurações":
    st.subheader("Configurações do Perfil")
    with st.form("f_conf"):
        v_h = st.number_input("Valor da Hora (R$)", value=st.session_state.v_hora)
        if st.form_submit_button("Salvar Valor"):
            df_u = buscar_dados("Usuarios")
            df_u.loc[df_u['usuario'] == st.session_state.usuario, 'valor_hora'] = v_h
            salvar_dados("Usuarios", df_u)
            st.session_state.v_hora = v_h
            st.success("Valor atualizado!")

    st.divider()
    # --- TROCAR SENHA (CORRIGIDO) ---
    with st.expander("🔐 Trocar Senha"):
        with st.form("f_pass"):
            pa = st.text_input("Senha Atual", type="password")
            pn = st.text_input("Nova Senha", type="password")
            if st.form_submit_button("Atualizar Senha"):
                df_u = buscar_dados("Usuarios")
                # Filtra o índice correto do usuário
                idx_user = df_u[df_u['usuario'] == st.session_state.usuario].index
                if str(df_u.loc[idx_user, 'senha'].values[0]) == pa:
                    df_u.loc[idx_user, 'senha'] = pn
                    salvar_dados("Usuarios", df_u)
                    st.success("Senha alterada com sucesso!")
                else:
                    st.error("Senha atual incorreta.")
