"""App del hogar.

Fase 2, primera entrega: stock del hogar.
  - Stock: cada artículo se marca como "Hay", "Queda poco" o "Falta".
  - Lista de compras: lo que está en "Queda poco" o "Falta".
  - Revisar artículos: aprobar lo que se propuso desde la pantalla de stock.
  - Estado: control de conexión y de tablas (solo administrador).
Qué ve cada persona lo decide la base de datos según su rol, no esta pantalla.
"""
import datetime as dt

import requests
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Hogar", page_icon="🏠", layout="centered")

URL = st.secrets.get("SUPABASE_URL", "")
KEY = st.secrets.get("SUPABASE_KEY", "")

if not URL or not KEY:
    st.error(
        "Faltan las claves de conexión. En Streamlit: Settings → Secrets, "
        "cargar SUPABASE_URL y SUPABASE_KEY."
    )
    st.stop()

if "cliente" not in st.session_state:
    st.session_state.cliente = create_client(URL, KEY)
    st.session_state.usuario = None
cliente = st.session_state.cliente

ETIQUETA = {"hay": "Hay", "queda_poco": "Queda poco", "falta": "Falta"}
CLAVE = {v: k for k, v in ETIQUETA.items()}


def pedir(fn):
    """Ejecuta una consulta; si la sesión venció, la renueva y reintenta una vez."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        texto = str(e)
        if "JWT" in texto or "401" in texto or "expired" in texto.lower():
            cliente.auth.refresh_session()
            return fn()
        raise


def ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------- ingreso
if st.session_state.usuario is None:
    st.title("Hogar")
    with st.form("ingreso"):
        correo = st.text_input("Correo")
        clave = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Entrar", use_container_width=True)
    if entrar:
        try:
            cliente.auth.sign_in_with_password({"email": correo.strip(), "password": clave})
            fila = cliente.table("usuarios").select("nombre, rol").execute().data
        except Exception:  # noqa: BLE001
            fila = None
            st.error("Correo o contraseña incorrectos.")
        if fila:
            st.session_state.usuario = fila[0]
            st.rerun()
        elif fila is not None:
            cliente.auth.sign_out()
            st.error("El usuario existe pero no está habilitado en la app.")
    st.stop()

usuario = st.session_state.usuario
rol = usuario["rol"]


# ---------------------------------------------------------------- datos de stock
def leer_stock():
    grupos = pedir(lambda: cliente.table("stock_grupos").select("id, nombre, orden").order("orden").execute().data)
    articulos = pedir(
        lambda: cliente.table("stock_articulos")
        .select("id, nombre, grupo_id, subgrupo, sinonimos, pendiente_revision")
        .eq("activo", True)
        .order("nombre")
        .execute()
        .data
    )
    abiertos = pedir(
        lambda: cliente.table("stock_reportes")
        .select("id, articulo_id, estado, reportado_en")
        .is_("repuesto_en", "null")
        .execute()
        .data
    )
    return grupos, articulos, {r["articulo_id"]: r for r in abiertos}


def aplicar_estado(articulo_id: int, nuevo: str, abierto):
    """Lleva un artículo al estado pedido. 'hay' cierra el aviso abierto."""
    if nuevo == "hay":
        if abierto:
            pedir(lambda: cliente.table("stock_reportes").update({"repuesto_en": ahora()}).eq("id", abierto["id"]).execute())
    elif abierto is None:
        pedir(lambda: cliente.table("stock_reportes").insert({"articulo_id": articulo_id, "estado": nuevo}).execute())
    elif abierto["estado"] != nuevo:
        pedir(lambda: cliente.table("stock_reportes").update({"estado": nuevo}).eq("id", abierto["id"]).execute())


def al_cambiar(articulo_id: int):
    elegido = st.session_state.get(f"art_{articulo_id}")
    if elegido is None:  # tocar la opción ya marcada la desmarca: no es un cambio
        return
    abierto = st.session_state.abiertos.get(articulo_id)
    try:
        aplicar_estado(articulo_id, CLAVE[elegido], abierto)
    except Exception as e:  # noqa: BLE001
        st.session_state.aviso = f"No se pudo guardar el cambio ({type(e).__name__}). Probá de nuevo."


# ---------------------------------------------------------------- pantallas
def pantalla_stock():
    grupos, articulos, abiertos = leer_stock()
    st.session_state.abiertos = abiertos

    faltan = sum(1 for r in abiertos.values() if r["estado"] == "falta")
    poco = sum(1 for r in abiertos.values() if r["estado"] == "queda_poco")
    st.caption(f"Faltan: {faltan} · Queda poco: {poco}")

    if st.session_state.get("aviso"):
        st.error(st.session_state.pop("aviso"))

    buscar = st.text_input("Buscar", placeholder="Escribí el nombre: leche, jabón, coca…").strip().lower()
    nombres = [g["nombre"] for g in grupos]
    grupo_por_id = {g["id"]: g["nombre"] for g in grupos}

    if buscar:
        def coincide(a):
            textos = [a["nombre"]] + (a.get("sinonimos") or [])
            return any(buscar in t.lower() for t in textos)

        visibles = [a for a in articulos if coincide(a)]
        if not visibles:
            st.info("No hay ningún artículo con ese nombre. Podés proponerlo más abajo.")
    else:
        elegido = st.pills("Lugar de la casa", nombres, default=nombres[0] if nombres else None, key="grupo")
        if elegido is None and nombres:
            elegido = nombres[0]
        visibles = [a for a in articulos if grupo_por_id.get(a["grupo_id"]) == elegido]

    subgrupo_actual = object()
    for a in sorted(visibles, key=lambda x: (x.get("subgrupo") or "", x["nombre"])):
        if not buscar and a.get("subgrupo") != subgrupo_actual:
            subgrupo_actual = a.get("subgrupo")
            if subgrupo_actual:
                st.markdown(f"**{subgrupo_actual}**")
        abierto = abiertos.get(a["id"])
        estado = abierto["estado"] if abierto else "hay"
        llave = f"art_{a['id']}"
        st.session_state[llave] = ETIQUETA[estado]
        titulo = a["nombre"] + (" · pendiente de aprobación" if a["pendiente_revision"] else "")
        if buscar:
            titulo += f"  ({grupo_por_id.get(a['grupo_id'], '')})"
        st.segmented_control(
            titulo, list(ETIQUETA.values()), key=llave, on_change=al_cambiar, args=(a["id"],)
        )

    with st.expander("¿Falta algo que no está en la lista?"):
        with st.form("proponer", clear_on_submit=True):
            nombre = st.text_input("Nombre del artículo")
            lugar = st.selectbox("Lugar de la casa", nombres)
            enviar = st.form_submit_button("Agregar", use_container_width=True)
        if enviar:
            nombre = " ".join(nombre.split())
            if not nombre:
                st.warning("Escribí el nombre del artículo.")
            elif any(nombre.lower() == a["nombre"].lower() for a in articulos):
                st.warning("Ese artículo ya está en la lista. Buscalo arriba.")
            else:
                grupo_id = next(g["id"] for g in grupos if g["nombre"] == lugar)
                try:
                    pedir(
                        lambda: cliente.table("stock_articulos")
                        .insert({"nombre": nombre, "grupo_id": grupo_id, "pendiente_revision": True})
                        .execute()
                    )
                except Exception as e:  # noqa: BLE001
                    st.error(f"No se pudo agregar ({type(e).__name__}).")
                else:
                    st.rerun()


def pantalla_lista():
    filas = pedir(lambda: cliente.table("v_lista_compras").select("*").order("orden").execute().data)
    if not filas:
        st.success("No hay nada para reponer.")
        return
    st.caption(f"{len(filas)} artículo(s) para reponer. Tildá lo que ya se compró.")
    texto = []
    grupo = None
    for f in sorted(filas, key=lambda x: (x["orden"], x["estado"] != "falta", x["articulo"])):
        if f["grupo"] != grupo:
            grupo = f["grupo"]
            st.markdown(f"**{grupo}**")
            texto.append(f"\n{grupo}")
        marca = "FALTA" if f["estado"] == "falta" else "queda poco"
        detalle = " · ".join(x for x in [f.get("presentacion"), f.get("marca_preferida")] if x)
        etiqueta = f"{f['articulo']} — {marca}" + (f"  ({detalle})" if detalle else "")
        texto.append(f"- {f['articulo']} ({marca})")
        if st.checkbox(etiqueta, key=f"rep_{f['reporte_id']}"):
            pedir(lambda: cliente.table("stock_reportes").update({"repuesto_en": ahora()}).eq("id", f["reporte_id"]).execute())
            st.rerun()
    with st.expander("Lista en texto, para copiar y enviar"):
        st.code("Lista de compras" + "\n".join(texto), language=None)


def pantalla_revisar():
    pendientes = pedir(
        lambda: cliente.table("stock_articulos")
        .select("id, nombre, grupo_id, creado_en")
        .eq("pendiente_revision", True)
        .eq("activo", True)
        .order("creado_en")
        .execute()
        .data
    )
    if not pendientes:
        st.success("No hay artículos pendientes de aprobación.")
        return
    grupos = {g["id"]: g["nombre"] for g in pedir(lambda: cliente.table("stock_grupos").select("id, nombre").execute().data)}
    for p in pendientes:
        st.markdown(f"**{p['nombre']}** · {grupos.get(p['grupo_id'], '')}")
        decision = st.segmented_control(
            "Decisión", ["Aprobar", "Descartar"], key=f"rev_{p['id']}", label_visibility="collapsed"
        )
        if decision == "Aprobar":
            pedir(lambda: cliente.table("stock_articulos").update({"pendiente_revision": False}).eq("id", p["id"]).execute())
            st.rerun()
        elif decision == "Descartar":
            pedir(lambda: cliente.table("stock_articulos").update({"activo": False}).eq("id", p["id"]).execute())
            st.rerun()


def pantalla_estado():
    try:
        r = requests.get(f"{URL}/auth/v1/settings", headers={"apikey": KEY}, timeout=10)
        ok = r.status_code == 200
    except requests.RequestException:
        ok = False
    (st.success if ok else st.error)("Conexión con la base: " + ("correcta." if ok else "falló."))
    for tabla in ["cuentas", "categorias", "ingresos", "egresos", "stock_articulos", "stock_reportes", "usuarios"]:
        try:
            n = pedir(lambda: cliente.table(tabla).select("id", count="exact").limit(1).execute().count)
            st.write(f"- `{tabla}`: {n} filas")
        except Exception as e:  # noqa: BLE001
            st.write(f"- `{tabla}`: sin acceso ({type(e).__name__})")


# ---------------------------------------------------------------- navegación
PANTALLAS = {"Stock": pantalla_stock}
if rol in ("admin", "familia"):
    PANTALLAS["Lista de compras"] = pantalla_lista
    PANTALLAS["Revisar artículos"] = pantalla_revisar
if rol == "admin":
    PANTALLAS["Estado"] = pantalla_estado

st.title("Hogar")
if len(PANTALLAS) > 1:
    seccion = st.segmented_control("Sección", list(PANTALLAS), default="Stock", key="seccion", label_visibility="collapsed")
    seccion = seccion or "Stock"
else:
    seccion = "Stock"

PANTALLAS[seccion]()

st.divider()
st.caption(f"Sesión de {usuario['nombre']}")
if st.button("Salir"):
    cliente.auth.sign_out()
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()
