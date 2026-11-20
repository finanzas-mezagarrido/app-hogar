# App del hogar

Aplicación Streamlit para llevar ingresos, egresos, flujo de caja y stock de un hogar.
Los datos viven en una base PostgreSQL (Supabase) y solo se accede con usuario y contraseña;
este repositorio contiene únicamente el código de las pantallas.

Las claves de conexión no se guardan aquí: van en los secretos de Streamlit
(`SUPABASE_URL` y `SUPABASE_KEY`).
