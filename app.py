import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÃO DE LIMPEZA E BUSCA ---
def buscar_dados_limpos(aba):
    df = conn.read(worksheet=aba, ttl=0)
    if aba == "Lancamentos":
        # 1. Limpa espaços e acentos dos nomes das colunas
        df.columns = df.columns.str.strip()
        # 2. Converte as horas: troca vírgula por ponto e força ser número
        df['horas'] = df['horas'].astype(str).str.replace(',', '.')
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0)
        # 3. Limpa a coluna 'tipo' (remove espaços, acentos e deixa minúsculo)
        df['tipo_limpo'] = df['tipo'].astype(str).str.strip().str.lower()
        df['tipo_limpo'] = df['tipo_limpo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8')
    return df

def salvar_dados(df_novo):
    # Remove colunas auxiliares antes de subir para o Google
    colunas_para_remover = ['tipo_limpo', 'data_dt', 'cota_acumulada']
    df_para_salvar = df_novo.drop(columns=[c for c in colunas_para_remover if c in df_novo.columns])
    conn.update(worksheet="Lancamentos", data=df_para_salvar)
    st.cache_data.clear()

# --- REGRAS FINANCEIRAS ---
def calcular_imposto_total(valor_bruto):
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
if not st.session_state.logado:
    st.title("🔐 Login")
    with st.form("l"):
        u, p = st.text_input("Usuário").lower().strip(), st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados_limpos("Usuarios")
            if not df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)].empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = df_u[df_u['usuario']==u]['nome_exibicao'].values[0]
                st.rerun()
            else: st.error("Acesso Negado")
    st.stop()

# --- CÁLCULO DA REGRA ---
v_hora = st.sidebar.number_input("Valor Hora (R$)", min_value=0.0, value=25.0)
df_todos = buscar_dados_limpos("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

# Lógica Simplificada e Robusta
if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.sort_values('data_dt')

    # 1. Identifica Créditos e Débitos
    creditos = df_user[df_user['tipo_limpo'] == "credito"].copy()
    debitos = df_user[df_user['tipo_limpo'] == "debito"].copy()

    # 2. Soma de Créditos Acumulada (A cota que nunca desce)
    creditos['cota_acumulada'] = creditos['horas'].cumsum()
    
    # 3. Separa o que é Banco do que é Dinheiro
    def separar_banco(row):
        anterior = row['cota_acumulada'] - row['horas']
        if anterior >= 36: return 0, row['horas'] # Tudo dinheiro
        if row['cota_acumulada'] <= 36: return row['horas'], 0 # Tudo banco
        vaga = 36 - anterior
        return vaga, row['horas'] - vaga # Divide
    
    if not creditos.empty:
        creditos[['h_banco', 'h_pago']] = creditos.apply(separar_banco, axis=1, result_type='expand')
        total_h_banco = creditos['h_banco'].sum()
        total_h_pagas = creditos['h_pago'].sum()
    else:
        total_h_banco = total_h_pagas = 0

    # 4. Soma de Débitos
    total_debitos = debitos['horas'].sum()
    
    # 5. Saldo Final (Créditos do banco - Débitos)
    saldo_folgas = total_h_banco - total_debitos
else:
    total_h_banco = total_h_pagas = total_debitos = saldo_folgas = 0

# Financeiro
bruto_ex = total_h_pagas * (v_hora * 2.1)
imp_b = calcular_imposto_total(v_hora * 220)
imp_t = calcular_imposto_total((v_hora * 220) + bruto_ex)
liq_ex = bruto_ex - (imp_t - imp_b)

# --- INTERFACE ---
st.title("Banco de Horas e Extras")
t1, t2, t3 = st.tabs(["➕ Créditos", "➖ Folgas", "📊 Extrato"])

with t1:
    st.metric("Cota Consumida", f"{total_h_banco:.2f} / 36.00h")
    with st.form("f1"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent, sai = c1.time_input("Entrada", value=time(8,0)), c2.time_input("Saída", value=time(17,0))
        alm = st.checkbox("Almoço?", value=True)
        if st.form_submit_button("Lançar"):
            h = (datetime.combine(d, sai) - datetime.combine(d, ent)).total_seconds() / 3600
            if alm: h -= 1
            mult = 1.5 if d.weekday() == 5 else 1.25
            h_calc = min(h * mult, 2.0) if d.weekday() <= 4 else h * mult
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h_calc}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with t2:
    st.metric("Saldo para Folgas", f"{saldo_folgas:.2f}h")
    with st.form("f2"):
        dn = st.date_input("Data Folga")
        tipo_f = st.radio("Tipo", ["Dia Inteiro", "Parcial"])
        if tipo_f == "Parcial":
            c1, c2 = st.columns(2)
            en, sn = c1.time_input("Início", value=time(8,0)), c2.time_input("Fim", value=time(12,0))
        if st.form_submit_button("Lançar Folga"):
            if tipo_f == "Dia Inteiro": hf = 9.0 if dn.weekday() <= 3 else 8.0
            else: hf = (datetime.combine(dn, sn) - datetime.combine(dn, en)).total_seconds() / 3600
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": dn.strftime("%d/%m/%Y"), 
                                  "entrada": "Folga", "saida": "Parcial" if tipo_f == "Parcial" else "Integral", 
                                  "tipo": "Débito", "horas": hf}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with t3:
    st.subheader("Resumo Financeiro")
    col1, col2 = st.columns(2); col1.metric("Horas em R$", f"{total_h_pagas:.2f}h"); col2.metric("Líquido", f"R$ {liq_ex:,.2f}")
    st.divider()
    st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
    if st.button("🚨 ZERAR TUDO", type="primary"):
        salvar_dados(df_todos[df_todos['usuario'] != st.session_state.usuario])
        st.rerun()
