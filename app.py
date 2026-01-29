import streamlit as st
import pandas as pd
from datetime import datetime, time

# --- CONFIGURAÇÕES ---
st.set_page_config(page_title="Controle de Banco de Horas", layout="centered")

# --- LÓGICA DE CÁLCULO ---

def calcular_horas_positivas(data, entrada, saida, descontar_almoco):
    t1 = datetime.combine(data, entrada)
    t2 = datetime.combine(data, saida)
    diff = t2 - t1
    
    total_segundos = diff.total_seconds()
    if descontar_almoco:
        total_segundos -= 3600  # -1 hora
    
    horas_decimais = max(0, total_segundos / 3600)

    # Regra do Sábado (Multiplicador 1.5)
    if data.weekday() == 5: 
        horas_decimais *= 1.5

    return horas_decimais

def calcular_debito_folga(data, inteira=False, entrada=None, saida=None, almoco=False):
    if inteira:
        dia_semana = data.weekday()  # 0=Segunda, 4=Sexta
        if dia_semana <= 3:          # Segunda a Quinta
            return -9.0
        elif dia_semana == 4:        # Sexta
            return -8.0
        else:
            return 0.0               # Sáb/Dom (ajustar se necessário)
    else:
        # Cálculo para saída antecipada ou atraso (parcial)
        t1 = datetime.combine(data, entrada)
        t2 = datetime.combine(data, saida)
        diff = t2 - t1
        total_segundos = diff.total_seconds()
        if almoco:
            total_segundos -= 3600
        return -(total_segundos / 3600)

# --- INTERFACE ---

if 'logado' not in st.session_state:
    st.session_state.logado = False

# (Omitindo bloco de login para focar na nova lógica, mas ele permanece igual)
if not st.session_state.logado:
    st.session_state.logado = True # Apenas para visualização neste exemplo
    st.session_state.usuario = "Denise"

if 'db_horas' not in st.session_state:
    st.session_state.db_horas = pd.DataFrame(columns=["Data", "Tipo", "Horas"])

saldo_atual = st.session_state.db_horas["Horas"].sum()

st.title(f"Controle de Horas - {st.session_state.usuario}")
tab1, tab2, tab3 = st.tabs(["➕ Horas Positivas", "➖ Horas Negativas", "📊 Saldo e Extrato"])

# --- ABA 1: POSITIVAS ---
with tab1:
    with st.form("form_positivo"):
        data_p = st.date_input("Data do Lançamento")
        col1, col2 = st.columns(2)
        ent_p = col1.time_input("Entrada", value=time(8, 0))
        sai_p = col2.time_input("Saída", value=time(17, 0))
        almoco_p = st.checkbox("Descontar Almoço?", value=True)
        
        if st.form_submit_button("Registrar Crédito"):
            h_calc = calcular_horas_positivas(data_p, ent_p, sai_p, almoco_p)
            
            if saldo_atual + h_calc > 36:
                h_calc = 36 - saldo_atual
                st.warning("Limite de 36h atingido. Lançamento limitado ao saldo máximo.")
            
            if h_calc > 0:
                nova = pd.DataFrame([{"Data": data_p, "Tipo": "Positivo", "Horas": h_calc}])
                st.session_state.db_horas = pd.concat([st.session_state.db_horas, nova], ignore_index=True)
                st.success(f"Crédito de {h_calc:.2f}h registrado!")

# --- ABA 2: NEGATIVAS (COM A NOVA REGRA) ---
with tab2:
    tipo_folga = st.radio("Tipo de débito:", ["Dia Inteiro", "Parcial (Atraso/Saída Cedo)"])
    
    with st.form("form_negativo"):
        data_n = st.date_input("Data da Folga/Atraso")
        h_debito = 0
        
        if tipo_folga == "Parcial (Atraso/Saída Cedo)":
            col1, col2 = st.columns(2)
            ent_n = col1.time_input("Início do período", value=time(8, 0))
            sai_n = col2.time_input("Fim do período", value=time(12, 0))
            almoco_n = st.checkbox("Descontar Almoço?", value=False)
        
        if st.form_submit_button("Registrar Débito"):
            if tipo_folga == "Dia Inteiro":
                h_debito = calcular_debito_folga(data_n, inteira=True)
            else:
                h_debito = calcular_debito_folga(data_n, inteira=False, entrada=ent_n, saida=sai_n, almoco=almoco_n)
            
            # Validação do Limite de -36h
            if saldo_atual + h_debito < -36:
                h_debito = -36 - saldo_atual
                st.warning("Limite negativo de -36h atingido.")

            if h_debito != 0:
                nova = pd.DataFrame([{"Data": data_n, "Tipo": "Negativo", "Horas": h_debito}])
                st.session_state.db_horas = pd.concat([st.session_state.db_horas, nova], ignore_index=True)
                st.success(f"Débito de {abs(h_debito):.2f}h registrado!")

# --- ABA 3: SALDO ---
with tab3:
    st.metric("Saldo Acumulado", f"{saldo_atual:.2f} h", delta_color="normal")
    if st.button("Ver Extrato"):
        st.table(st.session_state.db_horas)
