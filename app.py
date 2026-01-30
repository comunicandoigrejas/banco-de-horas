import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ISOSED - Banco & Financeiro", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE CÁLCULO DE IMPOSTOS (TABELAS 2026) ---

def calcular_imposto_total(valor_bruto):
    """Calcula o total de INSS + IRPF para um valor bruto dado."""
    # 1. INSS PROGRESSIVO
    inss = 0
    base_inss = valor_bruto
    faixas_inss = [(1518.00, 0.075), (2800.00, 0.09), (4200.00, 0.12), (8157.00, 0.14)]
    anterior = 0
    for limite, aliquota in faixas_inss:
        if base_inss > limite:
            inss += (limite - anterior) * aliquota
            anterior = limite
        else:
            inss += (base_inss - anterior) * aliquota
            break
    
    # 2. IRPF PROGRESSIVO
    base_irpf = valor_bruto - inss
    irpf = 0
    if base_irpf > 4664.68: irpf = (base_irpf * 0.275) - 893.66
    elif base_irpf > 3751.05: irpf = (base_irpf * 0.225) - 662.77
    elif base_irpf > 2826.65: irpf = (base_irpf * 0.15) - 381.44
    elif base_irpf > 2259.20: irpf = (base_irpf * 0.075) - 169.44
    
    return round(inss + max(0, irpf), 2)

# --- FUNÇÕES DE BANCO ---

def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_logic(data, entrada, saida, almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada); t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if almoco: diff -= 1
    brutas = max(0, diff)
    
    if tipo == "positivo":
        if data.weekday() <= 4: # Semana (Limite 2h já com 1.25x)
            return min(brutas * 1.25, 2.0)
        elif data.weekday() == 5: # Sábado (1.5x)
            return brutas * 1.5
    return brutas

# --- LOGIN ---
if 'logado' not in st.session_state: st.session_state.logado = False
if not st.session_state.logado:
    st.title("🔐 Login ISOSED")
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
            else: st.error("Acesso negado")
    st.stop()

# --- SIDEBAR FINANCEIRA ---
st.sidebar.title("Configurações")
v_hora = st.sidebar.number_input("Valor da Hora (R$)", min_value=0.0, value=20.0)
salario_base = v_hora * 220
st.sidebar.write(f"Salário Base Est.: **R$ {salario_base:,.2f}**")

# --- PROCESSAMENTO ---
df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario]

# Lógica de Separação (Banco vs Pago)
acc_historico = 0
h_banco = 0
h_pagas = 0

for idx, row in df_user.iterrows():
    if row['tipo'] == "Crédito":
        if acc_historico < 36:
            vaga = 36 - acc_historico
            h_banco += min(row['horas'], vaga)
            h_pagas += max(0, row['horas'] - vaga)
            acc_historico += row['horas']
        else:
            h_pagas += row['horas']
    elif row['tipo'] == "Débito":
        h_banco -= row['horas']

# --- CÁLCULO FINANCEIRO REAL ---
# Valor da hora extra paga (110% = 2.1x)
bruto_extras = h_pagas * (v_hora * 2.1)
total_bruto_mensal = salario_base + bruto_extras

# Imposto apenas sobre o salário
imp_base = calcular_imposto_total(salario_base)
# Imposto sobre tudo (Salário + Extras)
imp_total = calcular_imposto_total(total_bruto_mensal)
# O imposto que "sobrou" é das horas extras
desconto_nas_extras = imp_total - imp_base
liquido_extras = bruto_extras - desconto_nas_extras

# --- INTERFACE ---
st.title("Controle de Ponto e Financeiro")
tab1, tab2, tab3 = st.tabs(["➕ Lançar Horas", "➖ Lançar Folga", "💰 Extrato & Pagamento"])

with tab1:
    st.info(f"Horas no Banco: **{h_banco:.2f}h** | Horas para Pagamento: **{h_pagas:.2f}h**")
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent, sai = c1.time_input("Entrada", value=time(8,0), step=300), c2.time_input("Saída", value=time(17,0), step=300)
        alm = st.checkbox("Almoço?", value=True)
        if st.form_submit_button("Registrar"):
            h = calcular_horas_logic(d, ent, sai, alm, "positivo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab3:
    st.subheader("📊 Resumo de Horas Extras Pagas (Excesso > 36h)")
    col1, col2, col3 = st.columns(3)
    col1.metric("Bruto (110%)", f"R$ {bruto_extras:,.2f}")
    col2.metric("Impostos (INSS/IR)", f"- R$ {desconto_nas_extras:,.2f}")
    col3.metric("Líquido Extra", f"R$ {liquido_extras:,.2f}", delta="A Receber")
    
    with st.expander("Ver detalhes do cálculo"):
        st.write(f"- Salário Base (220h): R$ {salario_base:,.2f}")
        st.write(f"- Multiplicador aplicado: 2.10 (Hora + 110%)")
        st.write(f"- Base de cálculo total para impostos: R$ {total_bruto_mensal:,.2f}")
    
    st.divider()
    st.subheader("📜 Histórico")
    st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
