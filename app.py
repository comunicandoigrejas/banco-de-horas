import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Banco de Horas e Extras", layout="centered")

# --- CONEXÃO E LIMPEZA ---
conn = st.connection("gsheets", type=GSheetsConnection)

def buscar_dados(aba):
    # ttl=0 força o Streamlit a buscar dados novos no Google Sheets toda vez
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    # Limpa o cache global para garantir que o próximo 'buscar_dados' venha fresco
    st.cache_data.clear()
    st.cache_resource.clear()

# --- REGRAS DE CÁLCULO ---
def calcular_impostos(valor_bruto):
    inss = 0
    faixas_inss = [(1518.0, 0.075), (2800.0, 0.09), (4200.0, 0.12), (8157.0, 0.14)]
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

def calcular_horas_regra(data, entrada, saida, almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada); t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if almoco: diff -= 1
    brutas = max(0, diff)
    
    if tipo == "positivo":
        if data.weekday() <= 4: # Semana: 1.25x (Limite 2h finais por dia)
            return min(brutas * 1.25, 2.0)
        elif data.weekday() == 5: # Sábado: 1.5x
            return brutas * 1.5
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
            else: st.error("Acesso Negado")
    st.stop()

# --- LÓGICA DE PROCESSAMENTO ---
v_hora = st.sidebar.number_input("Valor da Hora (R$)", min_value=0.0, value=25.0)
salario_base = v_hora * 220

df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

# Variáveis de controle
cota_acumulada = 0
saldo_folgas = 0
extras_dinheiro = 0

if not df_user.empty:
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    df_user = df_user.dropna(subset=['data_dt']).sort_values('data_dt')
    
    for _, row in df_user.iterrows():
        if row['tipo'] == "Crédito":
            if cota_acumulada < 36:
                vaga = 36 - cota_acumulada
                para_banco = min(row['horas'], vaga)
                para_dinheiro = max(0, row['horas'] - vaga)
                
                cota_acumulada += para_banco
                saldo_folgas += para_banco
                extras_dinheiro += para_dinheiro
            else:
                extras_dinheiro += row['horas']
        elif row['tipo'] == "Débito":
            saldo_folgas -= row['horas']

# Financeiro
bruto_extras = extras_dinheiro * (v_hora * 2.1)
imp_base = calcular_impostos(salario_base)
imp_total = calcular_impostos(salario_base + bruto_extras)
liquido_extras = bruto_extras - (imp_total - imp_base)

# --- INTERFACE ---
st.title("Banco de Horas e Extras")
tab1, tab2, tab3 = st.tabs(["➕ Créditos", "➖ Folgas", "📊 Extrato"])

with tab1:
    st.write(f"Cota de Banco: **{cota_acumulada:.2f} / 36.00h**")
    st.progress(min(1.0, cota_acumulada / 36))
    
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent = c1.time_input("Entrada", value=time(8,0), step=300)
        sai = c2.time_input("Saída", value=time(17,0), step=300)
        alm = st.checkbox("Descontar Almoço?", value=True)
        if st.form_submit_button("Registrar"):
            h = calcular_horas_regra(d, ent, sai, alm, "positivo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab2:
    st.write(f"Saldo para Folgas: **{saldo_folgas:.2f}h**")
    modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        d_n = st.date_input("Data da Folga")
        h_d, e_v, s_v = 0, "-", "-"
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en_n, sa_n = c1.time_input("Início", value=time(8,0), step=300), c2.time_input("Fim", value=time(12,0), step=300)
            e_v, s_v = en_n.strftime("%H:%M"), sa_n.strftime("%H:%M")
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro":
                h_d = 9.0 if d_n.weekday() <= 3 else 8.0
                e_v, s_v = "Folga", "Integral"
            else: h_d = calcular_horas_regra(d_n, en_n, sa_n, False, "negativo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                  "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": h_d}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab3:
    st.subheader("Resumo")
    m1, m2, m3 = st.columns(3)
    m1.metric("Saldo Folgas", f"{saldo_folgas:.2f}h")
    m2.metric("Horas em R$", f"{extras_dinheiro:.2f}h")
    m3.metric("Líquido Extra", f"R$ {liquido_extras:,.2f}")
    
    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        if st.button("🚨 ZERAR TODO O CICLO", type="primary"):
            # Deleta apenas os dados do usuário atual e limpa cache agressivamente
            df_final = df_todos[df_todos['usuario'] != st.session_state.usuario]
            salvar_dados(df_final)
            st.rerun()
