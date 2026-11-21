"""App del hogar.

Stock del hogar
  - Stock: quien está en la casa marca cada artículo como "Hay", "Queda poco"
    o "Falta", cuando quiere.
  - Faltantes: la familia ve lo marcado y decide qué se compra.
  - Lista de compras: lo decidido, a la vista de todos.
  - Revisar artículos: aprobar lo que se propuso desde la pantalla de stock.
Finanzas
  - Resumen del año: ingreso, gasto y ahorro por mes, con el gasto por grupo.
  - Importar: carga el ledger del sistema de la carpeta Finanzas (solo administrador).
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
        entrar = st.form_submit_button("Entrar", width="stretch")
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
            enviar = st.form_submit_button("Agregar", width="stretch")
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


DECISION = {"comprar": "Comprar", "no_por_ahora": "Por ahora no"}
CLAVE_DECISION = {v: k for k, v in DECISION.items()}


def al_decidir(reporte_id: int):
    elegido = st.session_state.get(f"dec_{reporte_id}")
    valor = CLAVE_DECISION[elegido] if elegido else None  # desmarcar = volver a "sin decidir"
    try:
        pedir(lambda: cliente.table("stock_reportes").update({"decision": valor}).eq("id", reporte_id).execute())
    except Exception as e:  # noqa: BLE001
        st.session_state.aviso = f"No se pudo guardar la decisión ({type(e).__name__}). Probá de nuevo."


def al_anotar(reporte_id: int):
    texto = (st.session_state.get(f"cant_{reporte_id}") or "").strip()
    try:
        pedir(lambda: cliente.table("stock_reportes").update({"cantidad": texto or None}).eq("id", reporte_id).execute())
    except Exception as e:  # noqa: BLE001
        st.session_state.aviso = f"No se pudo guardar la cantidad ({type(e).__name__}). Probá de nuevo."


def leer_faltantes():
    filas = pedir(lambda: cliente.table("v_lista_compras").select("*").order("orden").execute().data)
    return sorted(filas, key=lambda x: (x["orden"], x["estado"] != "falta", x["articulo"]))


def pantalla_faltantes():
    """La familia mira lo que falta o queda poco y decide qué se compra."""
    filas = leer_faltantes()
    if st.session_state.get("aviso"):
        st.error(st.session_state.pop("aviso"))
    if not filas:
        st.success("No hay nada marcado como faltante ni por acabarse.")
        return
    sin_decidir = sum(1 for f in filas if not f.get("decision"))
    a_comprar = sum(1 for f in filas if f.get("decision") == "comprar")
    st.caption(f"{len(filas)} artículo(s) marcados · Sin decidir: {sin_decidir} · A comprar: {a_comprar}")

    ver = st.segmented_control("Mostrar", ["Sin decidir", "Todos"], default="Sin decidir", key="ver_faltantes", label_visibility="collapsed")
    if ver != "Todos":
        visibles = [f for f in filas if not f.get("decision")]
        if not visibles:
            st.success("Todo decidido. La lista de compras está en la sección «Lista de compras».")
    else:
        visibles = filas

    grupo = None
    for f in visibles:
        if f["grupo"] != grupo:
            grupo = f["grupo"]
            st.markdown(f"**{grupo}**")
        marca = "FALTA" if f["estado"] == "falta" else "queda poco"
        llave = f"dec_{f['reporte_id']}"
        st.session_state[llave] = DECISION.get(f.get("decision"))
        st.segmented_control(
            f"{f['articulo']} — {marca}", list(DECISION.values()), key=llave,
            on_change=al_decidir, args=(f["reporte_id"],),
        )
        if f.get("decision") == "comprar":
            llave_c = f"cant_{f['reporte_id']}"
            st.session_state[llave_c] = f.get("cantidad") or ""
            st.text_input(
                "Cantidad o aclaración", key=llave_c, placeholder="Cantidad o aclaración (opcional)",
                label_visibility="collapsed", on_change=al_anotar, args=(f["reporte_id"],),
            )


def pantalla_lista():
    """Lista de compras: lo que la familia decidió comprar. La ven todos."""
    filas = [f for f in leer_faltantes() if f.get("decision") == "comprar"]
    if st.session_state.get("aviso"):
        st.error(st.session_state.pop("aviso"))
    if not filas:
        st.info("Todavía no hay nada decidido para comprar.")
        return
    familia = rol in ("admin", "familia")
    st.caption(
        f"{len(filas)} artículo(s) para comprar."
        + (" Tildá lo que ya se compró." if familia else " Cuando llegue la compra, marcá «Hay» en Stock.")
    )
    texto = ["Lista de compras"]
    grupo = None
    for f in filas:
        if f["grupo"] != grupo:
            grupo = f["grupo"]
            st.markdown(f"**{grupo}**")
            texto.append(f"\n{grupo}")
        linea = f["articulo"] + (f" — {f['cantidad']}" if f.get("cantidad") else "")
        texto.append(f"- {linea}")
        if familia:
            if st.checkbox(linea, key=f"rep_{f['reporte_id']}"):
                pedir(lambda: cliente.table("stock_reportes").update({"repuesto_en": ahora()}).eq("id", f["reporte_id"]).execute())
                st.rerun()
        else:
            st.write(f"- {linea}")
    with st.expander("Lista en texto, para copiar y enviar"):
        st.code("\n".join(texto), language=None)


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


def gs(n) -> str:
    """Guaraníes con separador de miles."""
    return f"{int(round(n)):,}".replace(",", ".")


def pantalla_resumen():
    filas = pedir(lambda: cliente.table("v_resultado_mensual").select("*").order("mes").execute().data)
    if not filas:
        st.info("Todavía no hay movimientos cargados.")
        return
    st.caption(
        "Fondo común del hogar: lo que pasa por las cuentas cargadas. "
        "No incluye lo que Sofía cobra y paga desde sus propias cuentas."
    )
    tabla = [
        {
            "Mes": f["mes"][:7],
            "Ingreso": gs(f["ingreso"]),
            "Gasto": gs(f["gasto"]),
            "Ahorro": gs(f["ahorro"]),
            "Tasa de ahorro": "" if f["tasa_ahorro_pct"] is None else f"{float(f['tasa_ahorro_pct']):.1f} %",
        }
        for f in filas
    ]
    st.dataframe(tabla, hide_index=True, width="stretch")

    meses = [f["mes"][:7] for f in filas]
    mes = st.selectbox("Detalle del gasto de", meses, index=len(meses) - 1)
    detalle = pedir(
        lambda: cliente.table("v_gasto_por_grupo").select("*").eq("mes", f"{mes}-01").execute().data
    )
    por_grupo = {}
    for d in detalle:
        por_grupo.setdefault(d["grupo"], []).append(d)
    total = sum(d["gasto"] for d in detalle) or 1
    for grupo, items in sorted(por_grupo.items(), key=lambda kv: -sum(i["gasto"] for i in kv[1])):
        subtotal = sum(i["gasto"] for i in items)
        with st.expander(f"{grupo} — {gs(subtotal)}  ({100 * subtotal / total:.0f} %)"):
            for i in sorted(items, key=lambda i: -i["gasto"]):
                st.write(f"- {i['categoria']}: {gs(i['gasto'])}  ·  {i['movimientos']} mov.")


COLUMNAS_LEDGER = [
    "id_tx", "fecha", "fecha_caja", "mes", "fuente", "cuenta", "flujo", "flujo_origen", "importe",
    "categoria", "subcategoria", "contraparte", "descripcion_raw", "transferencia_interna", "compra_id",
    "cuota_n", "cuota_total", "estado", "fecha_cobro", "archivo_origen", "ambito", "capital",
    "interes_deuda", "tipo_gasto",
]


def pantalla_importar():
    import csv
    import io

    st.caption(
        "Carga el ledger del sistema de la carpeta Finanzas (sistema/data/ledger.csv). "
        "Se puede repetir cada mes: no duplica movimientos ni pisa lo corregido en la app."
    )
    archivo = st.file_uploader("Archivo ledger.csv", type=["csv"])
    if archivo is None:
        return
    try:
        lector = csv.DictReader(io.StringIO(archivo.getvalue().decode("utf-8-sig")))
        filas = [{c: (f.get(c) or "") for c in COLUMNAS_LEDGER} for f in lector]
        faltan = [c for c in COLUMNAS_LEDGER if c not in (lector.fieldnames or [])]
    except Exception as e:  # noqa: BLE001
        st.error(f"No se pudo leer el archivo ({type(e).__name__}).")
        return
    if faltan:
        st.error("El archivo no es el ledger esperado. Faltan columnas: " + ", ".join(faltan))
        return
    if not filas:
        st.error("El archivo no tiene movimientos.")
        return
    meses = sorted({f["mes"] for f in filas})
    st.write(f"{gs(len(filas))} movimientos, de {meses[0]} a {meses[-1]}.")

    if not st.button("Cargar en la base", type="primary", width="stretch"):
        return

    barra = st.progress(0.0, text="Reemplazando la copia del ledger…")
    pedir(lambda: cliente.table("ledger_importado").delete().neq("id_tx", "").execute())
    paso = 400
    for i in range(0, len(filas), paso):
        lote = filas[i : i + paso]
        pedir(lambda: cliente.table("ledger_importado").upsert(lote, on_conflict="id_tx").execute())
        barra.progress(min(1.0, (i + paso) / len(filas)), text=f"Subiendo movimientos… {min(i + paso, len(filas))} de {len(filas)}")
    barra.progress(1.0, text="Repartiendo en las tablas de la app…")
    resultado = pedir(lambda: cliente.rpc("migrar_ledger").execute().data)
    barra.empty()

    st.success(
        f"Migración hecha: {gs(resultado['egresos'])} egresos, {gs(resultado['ingresos'])} ingresos, "
        f"{gs(resultado['traspasos'])} traspasos y {gs(resultado['operaciones_patrimoniales'])} operaciones patrimoniales."
    )
    avisos = {
        "omitidos_importe_cero": "movimientos con importe cero, omitidos",
        "egresos_sin_cuenta": "egresos de una cuenta que la app no conoce, no cargados",
        "sin_categoria": "movimientos con una categoría que la app no conoce, cargados sin categoría",
        "ya_no_estan_en_el_ledger": "movimientos que están en la app y ya no figuran en el ledger",
    }
    for clave, texto in avisos.items():
        if resultado.get(clave):
            st.warning(f"{resultado[clave]} {texto}.")

    # Control: los totales por mes de la app tienen que coincidir con los del ledger
    del_ledger = {}
    for f in filas:
        if f["flujo"] in ("ingreso", "egreso"):
            m = del_ledger.setdefault(f["mes"], {"ingreso": 0.0, "egreso": 0.0})
            m[f["flujo"]] += float(f["importe"] or 0)
    en_app = {
        r["mes"][:7]: r
        for r in pedir(lambda: cliente.table("v_resultado_mensual").select("*").execute().data)
    }
    control, descuadres = [], 0
    for mes in sorted(del_ledger):
        a = en_app.get(mes, {"ingreso": 0, "gasto": 0})
        di = round(del_ledger[mes]["ingreso"]) - a["ingreso"]
        dg = round(del_ledger[mes]["egreso"]) - a["gasto"]
        descuadres += bool(di or dg)
        control.append({"Mes": mes, "Ingreso (ledger)": gs(del_ledger[mes]["ingreso"]), "Ingreso (app)": gs(a["ingreso"]),
                        "Gasto (ledger)": gs(del_ledger[mes]["egreso"]), "Gasto (app)": gs(a["gasto"]),
                        "Diferencia": gs(abs(di) + abs(dg))})
    if descuadres:
        st.error(f"{descuadres} mes(es) no coinciden con el ledger. Revisar antes de usar las cifras.")
    else:
        st.success(f"Control: los {len(control)} meses coinciden con el ledger, en ingreso y en gasto.")
    st.dataframe(control, hide_index=True, width="stretch")


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
    PANTALLAS["Faltantes"] = pantalla_faltantes
PANTALLAS["Lista de compras"] = pantalla_lista
if rol in ("admin", "familia"):
    PANTALLAS["Revisar artículos"] = pantalla_revisar
    PANTALLAS["Resumen del año"] = pantalla_resumen
if rol == "admin":
    PANTALLAS["Importar"] = pantalla_importar
    PANTALLAS["Estado"] = pantalla_estado

st.title("Hogar")
seccion = st.segmented_control("Sección", list(PANTALLAS), default="Stock", key="seccion", label_visibility="collapsed")
seccion = seccion or "Stock"

PANTALLAS[seccion]()

st.divider()
st.caption(f"Sesión de {usuario['nombre']}")
if st.button("Salir"):
    cliente.auth.sign_out()
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.rerun()
