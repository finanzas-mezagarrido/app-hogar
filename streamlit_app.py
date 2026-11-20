"""App del hogar.

Fase 2, primera entrega: stock del hogar.
  - Stock: cada artículo se marca como "Hay", "Queda poco" o "Falta".
  - Pedido de la semana: la familia arma una lista, quien está en la casa
    contesta artículo por artículo, y sale la lista de compras final.
  - Faltantes: todo lo que está en "Queda poco" o "Falta".
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


def pedido_abierto():
    filas = pedir(lambda: cliente.table("stock_consultas").select("*").neq("estado", "cerrada").execute().data)
    return filas[0] if filas else None


def al_responder(item_id: int):
    elegido = st.session_state.get(f"resp_{item_id}")
    if elegido is None:
        return
    try:
        pedir(lambda: cliente.table("stock_consulta_items").update({"respuesta": CLAVE[elegido]}).eq("id", item_id).execute())
    except Exception as e:  # noqa: BLE001
        st.session_state.aviso = f"No se pudo guardar la respuesta ({type(e).__name__}). Probá de nuevo."


def lista_final(items, nombre_de):
    """Lista de compras que sale del pedido contestado."""
    bloques = [
        ("Comprar: falta", "falta"),
        ("Comprar si conviene: queda poco", "queda_poco"),
        ("Sin contestar todavía", None),
        ("No hace falta: hay", "hay"),
    ]
    texto = ["Lista de compras de la semana"]
    for titulo, clave in bloques:
        grupo = sorted((i for i in items if i["respuesta"] == clave), key=lambda i: nombre_de(i))
        if not grupo:
            continue
        st.markdown(f"**{titulo}**")
        if clave in ("falta", "queda_poco"):
            texto.append(f"\n{titulo}")
        for i in grupo:
            linea = nombre_de(i) + (f" — {i['cantidad']}" if i.get("cantidad") else "")
            st.write(f"- {linea}")
            if clave in ("falta", "queda_poco"):
                texto.append(f"- {linea}")
    with st.expander("Lista en texto, para copiar y enviar"):
        st.code("\n".join(texto), language=None)


def pantalla_pedido():
    familia = rol in ("admin", "familia")
    pedido = pedido_abierto()

    if st.session_state.get("aviso"):
        st.error(st.session_state.pop("aviso"))

    if pedido is None:
        if not familia:
            st.info("No hay ningún pedido para revisar.")
            return
        st.info("No hay un pedido abierto.")
        if st.button("Empezar el pedido de la semana", use_container_width=True):
            pedir(lambda: cliente.table("stock_consultas").insert({"estado": "armando"}).execute())
            st.rerun()
        return

    grupos, articulos, _ = leer_stock()
    por_id = {a["id"]: a for a in articulos}
    items = pedir(
        lambda: cliente.table("stock_consulta_items")
        .select("id, articulo_id, cantidad, respuesta")
        .eq("consulta_id", pedido["id"])
        .execute()
        .data
    )

    def nombre_de(i):
        a = por_id.get(i["articulo_id"])
        return a["nombre"] if a else "(artículo no visible)"

    # ---- armando: solo la familia
    if pedido["estado"] == "armando":
        st.subheader("Armar el pedido")
        ya = {i["articulo_id"] for i in items}
        libres = sorted((a for a in articulos if a["id"] not in ya), key=lambda a: a["nombre"])
        with st.form("agregar_item", clear_on_submit=True):
            elegido = st.selectbox(
                "Artículo", libres, index=None, placeholder="Escribí para buscar…",
                format_func=lambda a: a["nombre"],
            )
            cantidad = st.text_input("Cantidad o aclaración (opcional)", placeholder="2 cajas, la marca de siempre…")
            if st.form_submit_button("Agregar al pedido", use_container_width=True):
                if elegido is None:
                    st.warning("Elegí un artículo.")
                else:
                    pedir(
                        lambda: cliente.table("stock_consulta_items")
                        .insert({"consulta_id": pedido["id"], "articulo_id": elegido["id"], "cantidad": cantidad.strip() or None})
                        .execute()
                    )
                    st.rerun()

        with st.expander("Agregar algo que no está en el catálogo"):
            with st.form("item_nuevo", clear_on_submit=True):
                nombre = st.text_input("Nombre del artículo")
                lugar = st.selectbox("Lugar de la casa", [g["nombre"] for g in grupos])
                cant2 = st.text_input("Cantidad o aclaración (opcional)")
                if st.form_submit_button("Crear y agregar", use_container_width=True):
                    nombre = " ".join(nombre.split())
                    existente = next((a for a in articulos if a["nombre"].lower() == nombre.lower()), None)
                    if not nombre:
                        st.warning("Escribí el nombre del artículo.")
                    elif existente and existente["id"] in ya:
                        st.warning("Ese artículo ya está en el pedido.")
                    else:
                        if existente:
                            art_id = existente["id"]
                        else:
                            grupo_id = next(g["id"] for g in grupos if g["nombre"] == lugar)
                            art_id = pedir(
                                lambda: cliente.table("stock_articulos")
                                .insert({"nombre": nombre, "grupo_id": grupo_id, "pendiente_revision": False})
                                .execute()
                                .data
                            )[0]["id"]
                        pedir(
                            lambda: cliente.table("stock_consulta_items")
                            .insert({"consulta_id": pedido["id"], "articulo_id": art_id, "cantidad": cant2.strip() or None})
                            .execute()
                        )
                        st.rerun()

        st.markdown(f"**En el pedido: {len(items)}**")
        for i in sorted(items, key=nombre_de):
            texto = nombre_de(i) + (f" — {i['cantidad']}" if i.get("cantidad") else "")
            if st.checkbox(f"Quitar: {texto}", key=f"quitar_{i['id']}"):
                pedir(lambda: cliente.table("stock_consulta_items").delete().eq("id", i["id"]).execute())
                st.rerun()
        if items and st.button("Enviar a revisar", type="primary", use_container_width=True):
            pedir(lambda: cliente.table("stock_consultas").update({"estado": "enviada"}).eq("id", pedido["id"]).execute())
            st.rerun()
        return

    # ---- enviada: se contesta artículo por artículo
    if pedido["estado"] == "enviada":
        contestados = sum(1 for i in items if i["respuesta"])
        st.subheader("Revisión de la semana")
        st.caption(f"Contestados: {contestados} de {len(items)}. Marcá cada artículo según lo que hay en la casa.")
        for i in sorted(items, key=lambda i: (i["respuesta"] is not None, nombre_de(i))):
            llave = f"resp_{i['id']}"
            st.session_state[llave] = ETIQUETA[i["respuesta"]] if i["respuesta"] else None
            titulo = nombre_de(i) + (f" — {i['cantidad']}" if i.get("cantidad") else "")
            st.segmented_control(titulo, list(ETIQUETA.values()), key=llave, on_change=al_responder, args=(i["id"],))
        if familia and contestados:
            st.divider()
            st.markdown("**Cómo viene la lista**")
            lista_final(items, nombre_de)
        return

    # ---- respondida: lista final a la vista de todos
    st.subheader("Lista de compras de la semana")
    lista_final(items, nombre_de)
    if familia:
        st.divider()
        if st.button("Cerrar este pedido", use_container_width=True):
            pedir(lambda: cliente.table("stock_consultas").update({"estado": "cerrada"}).eq("id", pedido["id"]).execute())
            st.rerun()


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
PANTALLAS = {"Stock": pantalla_stock, "Pedido de la semana": pantalla_pedido}
if rol in ("admin", "familia"):
    PANTALLAS["Faltantes"] = pantalla_lista
    PANTALLAS["Revisar artículos"] = pantalla_revisar
if rol == "admin":
    PANTALLAS["Estado"] = pantalla_estado

# Quien revisa la casa arranca en el pedido si hay uno esperando respuesta
inicio = "Stock"
if rol == "hogar" and "seccion" not in st.session_state:
    try:
        p = pedido_abierto()
        if p and p["estado"] == "enviada":
            inicio = "Pedido de la semana"
    except Exception:  # noqa: BLE001
        pass

st.title("Hogar")
seccion = st.segmented_control("Sección", list(PANTALLAS), default=inicio, key="seccion", label_visibility="collapsed")
seccion = seccion or inicio

PANTALLAS[seccion]()

st.divider()
st.caption(f"Sesión de {usuario['nombre']}")
if st.button("Salir"):
    cliente.auth.sign_out()
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()
