import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE APOIO ---

def buscar_dados(aba):
    # ttl=0 garante que ele não use memória antiga e busque o que está na planilha AGORA
    df = conn.read(worksheet=aba, ttl=0)
    if aba == "Lancamentos":
        # Força a coluna horas a ser número para evitar o erro de travar soma
        df['horas'] = pd.to_numeric(df['horas'], errors='coerce').fillna(0)
        # Normaliza a coluna tipo para evitar erro de acentuação
        df['tipo_limpo'] = df['tipo'].str.normalize('NFKD').str.encode('ascii', errors='ignore').str.decode('utf-8').str.lower()
    return df

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_imposto_total(valor_bruto):
    inss = 0
    faixas_inss = [(1518.00, 0.075), (2800.00, 0.09), (4200.00, 0.12), (8157.00, 0.14)]
    anterior = 0
    for limite, aliquota in faixas_inss:
        if valor_bruto > limite:
            inss += (limite - anterior) * aliquota
            anterior = limite
        else:
            inss += (valor_bruto - anterior) * aliquota
            break
    base_irpf = valor_bruto - inss
    irpf = 0
    if base_irpf > 4664.68: irpf = (base_irpf * 0.275) - 893.66
    elif base_irpf > 3751.05: irpf = (base_irpf * 0.225) - 662.77
    elif base_irpf > 2826.65: irpf = (base_irpf * 0.15) - 381.44
    elif base_irpf > 2259.20: irpf = (base_irpf * 0.075) - 169.44
    return inss + max(0, irpf)

def calcular_horas_trabalhadas(data, entrada, saida, almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada); t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if almoco: diff -= 1
    brutas = max(0, diff)
    if tipo == "positivo":
        if data.weekday() <= 4: return min(brutas * 1.25, 2.0)
        elif data.weekday() == 5: return brutas * 1.5
    return brutas

# --- LOGIN ---
if 'logado' not in st.session_state: st.session_state.logado = False
if not st.session_state.logado:
    st.title("🔐 Login")
    with st.form("l"):
        u = st.text_input("Usuário").lower().strip()
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            df_u = buscar_dados("Usuarios")
            valid = df_u[(df_u['usuario'] == u) & (df_u['senha'].astype(str) == p)]
            if not valid.empty:
                st.session_state.logado, st.session_state.usuario = True, u
                st.session_state.nome = valid.iloc[0]['nome_exibicao']
                st.rerun()
            else: st.error("Acesso negado")
    st.stop()

# --- SIDEBAR E PROCESSAMENTO ---
v_hora = st.sidebar.number_input("Valor da Hora (R$)", min_value=0.0, value=25.0)
salario_base = v_hora * 220

df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

# VARIÁVEIS DE REGRA
cota_credito_usada = 0.0  # Mão única (Cresce até 36)
saldo_folgas = 0.0        # Sobe e desce
horas_extras_pagas = 0.0  # Transbordo

if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.dropna(subset=['data_dt']).sort_values('data_dt')
    
    for _, row in df_user.iterrows():
        horas = float(row['horas'])
        # Crédito
        if row['tipo_limpo'] == "credito":
            if cota_credito_usada < 36:
                espaco = 36 - cota_credito_usada
                vai_pro_banco = min(horas, espaco)
                
                cota_credito_usada += vai_pro_banco
                saldo_folgas += vai_pro_banco
                horas_extras_pagas += max(0, horas - espaco)
            else:
                horas_extras_pagas += horas
        # Débito (Folga)
        elif row['tipo_limpo'] == "debito":
            saldo_folgas -= horas

# Financeiro
bruto_extras = horas_extras_pagas * (v_hora * 2.1)
imp_base = calcular_imposto_total(salario_base)
imp_total = calcular_imposto_total(salario_base + bruto_extras)
liquido_extras = bruto_extras - (imp_total - imp_base)

# --- INTERFACE ---
st.title("Banco de Horas e Extras")
tab1, tab2, tab3 = st.tabs(["➕ Lançar Crédito", "➖ Lançar Folga", "📊 Extrato"])

with tab1:
    st.info(f"Cota de Crédito Usada: **{cota_credito_usada:.2f} / 36.00h**")
    if cota_credito_usada >= 36: st.warning("Cota de banco cheia. Extras agora em R$.")
    
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent = c1.time_input("Entrada", value=time(8,0), step=300)
        sai = c2.time_input("Saída", value=time(17,0), step=300)
        alm = st.checkbox("Descontar Almoço?", value=True)
        if st.form_submit_button("Registrar"):
            h = calcular_horas_trabalhadas(d, ent, sai, alm, "positivo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h}])
            salvar_dados(pd.concat([df_todos.drop(columns=['tipo_limpo']), novo], ignore_index=True))
            st.rerun()

with tab2:
    st.subheader("Registrar Débito (Folga)")
    st.write(f"Saldo para folgas: **{saldo_folgas:.2f}h**")
    modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        d_n = st.date_input("Data do Débito")
        h_d, e_v, s_v = 0, "-", "-"
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en_n = c1.time_input("Início", value=time(8,0), step=300)
            sa_n = c2.time_input("Fim", value=time(12,0), step=300)
            e_v, s_v = en_n.strftime("%H:%M"), sa_n.strftime("%H:%M")
        
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro":
                h_d = 9.0 if d_n.weekday() <= 3 else 8.0
                e_v, s_v = "Folga", "Integral"
            else: h_d = calcular_horas_trabalhadas(d_n, en_n, sa_n, False, "negativo")
            
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                  "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": float(h_d)}])
            salvar_dados(pd.concat([df_todos.drop(columns=['tipo_limpo']), novo], ignore_index=True))
            st.rerun()

with tab3:
    st.subheader("📊 Resumo do Ciclo")
    c1, c2, c3 = st.columns(3)
    c1.metric("Saldo Folgas", f"{saldo_folgas:.2f}h")
    c2.metric("Horas em R$", f"{horas_extras_pagas:.2f}h")
    c3.metric("Líquido Extras", f"R$ {liquido_extras:,.2f}")
    
    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        if st.button("🚨 ZERAR TODO O CICLO", type="primary"):
            salvar_dados(df_todos[df_todos['usuario'] != st.session_state.usuario].drop(columns=['tipo_limpo']))
            st.rerun()
