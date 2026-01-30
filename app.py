import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO ---
st.set_page_config(page_title="ISOSED - Banco Fixo e Horas Extras", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE IMPOSTOS ---
def calcular_imposto_total(valor_bruto):
    """INSS e IRPF Progressivo 2026."""
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

# --- FUNÇÕES DE DADOS ---
def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_trabalhadas(data, entrada, saida, almoco, tipo="positivo"):
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
    st.title("🔐 Login de Acesso")
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
            else: st.error("Erro de Login")
    st.stop()

# --- SIDEBAR ---
v_hora = st.sidebar.number_input("Valor da Hora (R$)", min_value=0.0, value=25.0)
salario_base = v_hora * 220

# --- PROCESSAMENTO DA REGRA DE 36H FIXA ---
df_todos = buscar_data("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario].copy()

total_creditos_na_vida = 0
saldo_banco_disponivel = 0
horas_extras_pagas = 0

if not df_user.empty:
    # CORREÇÃO AQUI: dayfirst=True ajuda com o formato brasileiro e errors='coerce' evita o travamento
    df_user['data_dt'] = pd.to_datetime(df_user['data'], dayfirst=True, errors='coerce')
    
    # Remove linhas onde a data ficou inválida ou vazia na planilha
    df_user = df_user.dropna(subset=['data_dt'])
    
    # Ordena cronologicamente
    df_user = df_user.sort_values('data_dt')
    
    for _, row in df_user.iterrows():
        if row['tipo'] == "Crédito":
            if total_creditos_na_vida < 36:
                vaga_no_banco = 36 - total_creditos_na_vida
                ao_banco = min(row['horas'], vaga_no_banco)
                saldo_banco_disponivel += ao_banco
                horas_extras_pagas += max(0, row['horas'] - vaga_no_banco)
                total_creditos_na_vida += row['horas']
            else:
                horas_extras_pagas += row['horas']
                total_creditos_na_vida += row['horas']
        elif row['tipo'] == "Débito":
            saldo_banco_disponivel -= row['horas']
            
# --- CÁLCULO FINANCEIRO ---
# Hora Extra 110% (Valor * 2.1)
bruto_extras = horas_extras_pagas * (v_hora * 2.1)
total_bruto_mensal = salario_base + bruto_extras

imp_base = calcular_imposto_total(salario_base)
imp_total = calcular_imposto_total(total_bruto_mensal)
imposto_das_extras = imp_total - imp_base
liquido_extras = bruto_extras - imposto_das_extras

# --- INTERFACE ---
st.title("ISOSED - Gestão de Ponto")
tab1, tab2, tab3 = st.tabs(["➕ Créditos", "➖ Débitos", "💰 Extrato & Financeiro"])

with tab1:
    st.info(f"Cota de Banco utilizada: **{min(36.0, total_creditos_na_vida):.2f} / 36.00h**")
    if total_creditos_na_vida >= 36:
        st.warning("⚠️ Cota de 36h de banco esgotada. Novos créditos serão pagos como Horas Extras.")
    
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
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab2:
    st.subheader("Registrar Folga")
    modo = st.radio("Tipo:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        d_n = st.date_input("Data do Débito")
        h_d, e_v, s_v = 0, "-", "-"
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en_n, sa_n = c1.time_input("Início", value=time(8,0), step=300), c2.time_input("Fim", value=time(12,0), step=300)
            al_n = st.checkbox("Descontar Almoço?", value=False)
            e_v, s_v = en_n.strftime("%H:%M"), sa_n.strftime("%H:%M")
        
        if st.form_submit_button("Confirmar Débito"):
            if modo == "Dia Inteiro":
                h_d = 9.0 if d_n.weekday() <= 3 else 8.0
                e_v, s_v = "Folga", "Integral"
            else: h_d = calcular_horas_trabalhadas(d_n, en_n, sa_n, al_n, "negativo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                  "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": h_d}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

with tab3:
    st.subheader("💰 Resumo Financeiro")
    col1, col2, col3 = st.columns(3)
    # Mostra o saldo de folgas (que pode ser negativo)
    col1.metric("Saldo Banco (Folgas)", f"{saldo_banco_disponivel:.2f}h")
    col2.metric("Líquido Extra (110%)", f"R$ {liquido_extras:,.2f}")
    col3.metric("Impostos Retidos", f"R$ {imposto_das_extras:,.2f}")

    st.divider()
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        st.subheader("⚙️ Manutenção")
        # Botão Zerar reinicia a vida do banco (reseta a cota de 36h)
        if st.button("Zerar Todo o Banco e Cota", type="primary"):
            salvar_dados(df_todos[df_todos['usuario'] != st.session_state.usuario])
            st.rerun()

        st.divider()
        ops = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
        sel = st.selectbox("Apagar linha:", options=list(ops.keys()))
        if st.button("Remover Registro"):
            salvar_dados(df_todos.drop(ops[sel]))
            st.rerun()
