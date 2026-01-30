import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="ISOSED - Gestão de Ponto", layout="centered")
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNÇÕES DE CÁLCULO FINANCEIRO E IMPOSTOS ---

def calcular_imposto_total(valor_bruto):
    """Cálculo progressivo de INSS + IRPF (Tabelas 2026)."""
    # INSS
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
    
    # IRPF
    base_irpf = valor_bruto - inss
    irpf = 0
    if base_irpf > 4664.68: irpf = (base_irpf * 0.275) - 893.66
    elif base_irpf > 3751.05: irpf = (base_irpf * 0.225) - 662.77
    elif base_irpf > 2826.65: irpf = (base_irpf * 0.15) - 381.44
    elif base_irpf > 2259.20: irpf = (base_irpf * 0.075) - 169.44
    
    return inss + max(0, irpf)

# --- FUNÇÕES DE BANCO DE DADOS ---

def buscar_dados(aba):
    return conn.read(worksheet=aba, ttl=0)

def salvar_dados(df_novo):
    conn.update(worksheet="Lancamentos", data=df_novo)
    st.cache_data.clear()

def calcular_horas_logic(data, entrada, saida, almoco, tipo="positivo"):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = (t2 - t1).total_seconds() / 3600
    if almoco: diff -= 1
    brutas = max(0, diff)
    
    if tipo == "positivo":
        if data.weekday() <= 4: # Seg a Sex (Limite 2h já com 1.25x)
            return min(brutas * 1.25, 2.0)
        elif data.weekday() == 5: # Sábado (1.5x)
            return brutas * 1.5
    return brutas

# --- SISTEMA DE LOGIN ---
if 'logado' not in st.session_state:
    st.session_state.logado = False

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
            else:
                st.error("Usuário ou senha incorretos.")
    st.stop()

# --- CARREGAMENTO DE DADOS ---
v_hora = st.sidebar.number_input("Valor da sua Hora (R$)", min_value=0.0, value=25.0)
salario_base = v_hora * 220

df_todos = buscar_dados("Lancamentos")
df_user = df_todos[df_todos['usuario'] == st.session_state.usuario]

# --- LÓGICA DE DISTRIBUIÇÃO (BANCO VS PAGAMENTO) ---
acc_historico_creditos = 0
h_banco = 0
h_pagas = 0

for idx, row in df_user.iterrows():
    if row['tipo'] == "Crédito":
        if acc_historico_creditos < 36:
            vaga = 36 - acc_historico_creditos
            h_banco += min(row['horas'], vaga)
            h_pagas += max(0, row['horas'] - vaga)
            acc_historico_creditos += row['horas']
        else:
            h_pagas += row['horas']
    elif row['tipo'] == "Débito":
        h_banco -= row['horas']

saldo_banco_exibir = h_banco
total_bruto_extras = h_pagas * (v_hora * 2.1) # 110% de adicional

# --- INTERFACE ---
st.sidebar.write(f"👤 {st.session_state.nome}")
if st.sidebar.button("Sair"):
    st.session_state.logado = False
    st.rerun()

st.title("Controle de Ponto")
tab1, tab2, tab3 = st.tabs(["➕ Lançar Crédito", "➖ Lançar Folga", "📊 Extrato & Financeiro"])

# --- ABA 1: CRÉDITOS ---
with tab1:
    st.info(f"Créditos no Banco: **{h_banco:.2f}h** (Limite 36h) | Extras para Pagar: **{h_pagas:.2f}h**")
    with st.form("f_c"):
        d = st.date_input("Data")
        c1, c2 = st.columns(2)
        ent = c1.time_input("Entrada", value=time(8,0), step=300)
        sai = c2.time_input("Saída", value=time(17,0), step=300)
        alm = st.checkbox("Almoço?", value=True)
        if st.form_submit_button("Registrar"):
            h = calcular_horas_logic(d, ent, sai, alm, "positivo")
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d.strftime("%d/%m/%Y"), 
                                  "entrada": ent.strftime("%H:%M"), "saida": sai.strftime("%H:%M"), 
                                  "tipo": "Crédito", "horas": h}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

# --- ABA 2: FOLGAS (CORRIGIDA) ---
with tab2:
    st.subheader("Lançamento de Débitos")
    modo = st.radio("Selecione o tipo de falta:", ["Dia Inteiro", "Parcial"])
    with st.form("f_d"):
        d_n = st.date_input("Data da Folga")
        h_deb, e_v, s_v = 0, "-", "-"
        
        if modo == "Parcial":
            c1, c2 = st.columns(2)
            en_n = c1.time_input("Início", value=time(8,0), step=300)
            sa_n = c2.time_input("Fim", value=time(12,0), step=300)
            al_n = st.checkbox("Descontar Almoço?", value=False)
            e_v, s_v = en_n.strftime("%H:%M"), sa_n.strftime("%H:%M")
        
        if st.form_submit_button("Registrar Débito"):
            if modo == "Dia Inteiro":
                # Regra: Seg-Qui (0-3) = 9h | Sex (4) = 8h
                h_deb = 9.0 if d_n.weekday() <= 3 else 8.0
                e_v, s_v = "Folga", "Integral"
            else:
                h_deb = calcular_horas_logic(d_n, en_n, sa_n, al_n, "negativo")
            
            novo = pd.DataFrame([{"usuario": st.session_state.usuario, "data": d_n.strftime("%d/%m/%Y"), 
                                  "entrada": e_v, "saida": s_v, "tipo": "Débito", "horas": h_deb}])
            salvar_dados(pd.concat([df_todos, novo], ignore_index=True))
            st.rerun()

# --- ABA 3: EXTRATO, FINANCEIRO E EXCLUSÃO ---
with tab3:
    # Financeiro
    st.subheader("💰 Resumo de Pagamento (Excesso)")
    imp_base = calcular_imposto_total(salario_base)
    imp_total = calcular_imposto_total(salario_base + total_bruto_extras)
    desc_extras = imp_total - imp_base
    liquido_extras = total_bruto_extras - desc_extras

    c1, c2, c3 = st.columns(3)
    c1.metric("Banco (Saldo)", f"{saldo_banco_exibir:.2f}h", delta="Negativo" if saldo_banco_exibir < 0 else "Crédito")
    c2.metric("Bruto Extra (110%)", f"R$ {total_bruto_extras:,.2f}")
    c3.metric("Líquido Extra", f"R$ {liquido_extras:,.2f}")

    st.divider()
    st.subheader("📜 Histórico Detalhado")
    if not df_user.empty:
        st.dataframe(df_user[["data", "entrada", "saida", "tipo", "horas"]], use_container_width=True)
        
        st.divider()
        st.subheader("🗑️ Gerenciar Registros")
        
        # Função para zerar
        if st.button("Zerar Banco de Horas (Ajuste)"):
            if h_banco != 0:
                tipo_aj = "Débito" if h_banco > 0 else "Crédito"
                novo_aj = pd.DataFrame([{"usuario": st.session_state.usuario, "data": datetime.now().strftime("%d/%m/%Y"),
                                         "entrada": "AJUSTE", "saida": "ZERAR", "tipo": tipo_aj, "horas": abs(h_banco)}])
                salvar_dados(pd.concat([df_todos, novo_aj], ignore_index=True))
                st.rerun()

        # Função para excluir linha específica
        st.write("---")
        opcoes_del = {f"{r['data']} | {r['tipo']} | {r['horas']:.2f}h": i for i, r in df_user.iterrows()}
        item_sel = st.selectbox("Selecione um lançamento para apagar:", options=list(opcoes_del.keys()))
        if st.button("Apagar Registro Selecionado", type="primary"):
            df_final = df_todos.drop(opcoes_del[item_sel])
            salvar_dados(df_final)
            st.rerun()
    else:
        st.info("Nenhum lançamento encontrado.")
