"""Finanzas del hogar.

Fase 1: comprueba que la app publicada llega a la base de Supabase y que el
ingreso por usuario funciona. Las pantallas de carga y los tableros se agregan
en la Fase 2.
"""
import requests
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Finanzas del hogar", page_icon="🏠", layout="centered")
st.title("Finanzas del hogar")

URL = st.secrets.get("SUPABASE_URL", "")
KEY = st.secrets.get("SUPABASE_KEY", "")

if not URL or not KEY:
    st.error(
        "Faltan las claves de conexión. En Streamlit: Settings → Secrets, "
        "cargar SUPABASE_URL y SUPABASE_KEY."
    )
    st.stop()


def base_responde() -> bool:
    """Verdadero si Supabase contesta con esta dirección y esta clave."""
    try:
        r = requests.get(f"{URL}/auth/v1/settings", headers={"apikey": KEY}, timeout=10)
        return r.status_code == 200
    except requests.RequestException:
        return False


if "cliente" not in st.session_state:
    st.session_state.cliente = create_client(URL, KEY)
    st.session_state.usuario = None
cliente = st.session_state.cliente

if base_responde():
    st.success("Conexión con la base: correcta.")
else:
    st.error("No se pudo conectar con la base. Revisar SUPABASE_URL y SUPABASE_KEY.")
    st.stop()

if st.session_state.usuario is None:
    st.subheader("Ingresar")
    with st.form("ingreso"):
        correo = st.text_input("Correo")
        clave = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar")
    if entrar:
        try:
            cliente.auth.sign_in_with_password({"email": correo.strip(), "password": clave})
            fila = cliente.table("usuarios").select("nombre, rol").execute().data
            if not fila:
                cliente.auth.sign_out()
                st.error("El usuario existe pero no está habilitado en la app.")
            else:
                st.session_state.usuario = fila[0]
                st.rerun()
        except Exception:
            st.error("Correo o contraseña incorrectos.")
    st.stop()

usuario = st.session_state.usuario
st.write(f"Sesión de **{usuario['nombre']}** · rol **{usuario['rol']}**")

TABLAS = {
    "admin": ["cuentas", "categorias", "ingresos", "egresos", "stock_articulos", "stock_reportes"],
    "familia": ["cuentas", "categorias", "ingresos", "egresos", "stock_articulos", "stock_reportes"],
    "hogar": ["stock_articulos", "stock_reportes"],
}

st.subheader("Estado de la base")
for tabla in TABLAS.get(usuario["rol"], []):
    try:
        n = cliente.table(tabla).select("id", count="exact").limit(1).execute().count
        st.write(f"- `{tabla}`: {n} filas")
    except Exception as e:  # se muestra para poder corregirlo, no se oculta
        st.write(f"- `{tabla}`: sin acceso ({type(e).__name__})")

if st.button("Salir"):
    cliente.auth.sign_out()
    st.session_state.usuario = None
    st.rerun()
