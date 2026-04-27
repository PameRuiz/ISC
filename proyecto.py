import streamlit as st
import pandas as pd
import plotly.express as px
import json
import unicodedata
import re

# Configuración de la página
st.set_page_config(page_title="Dashboard Valencia Airbnb", layout="wide")

# Funcion para limpiar el texto eliminando acentos, caracteres especiales y 
# normalizando nombres de distritos para que coincidan con el GeoJSON
def clean_text(txt):
    if pd.isna(txt): return ""
    # Pasamos todo a mayusculas y eliminamos espacios al inicio y al final
    t = str(txt).upper().strip()
    # Eliminamos acentos y caracteres especiales utilizando unicodedata
    t = ''.join(c for c in unicodedata.normalize('NFD', t) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^A-Z0-9]', '', t)

# CARGA DE DATOS
# utilizamos la instruccion de cache_data para que no recargue los datos con cada interacción.
@st.cache_data
def cargar_datos():
    try:
        df_airbnb = pd.read_csv('lista_airbnb.csv')
        df_reviews = pd.read_csv('reviews.csv')
        df_historico = pd.read_csv('datos_barrios_valencia.csv') 
        with open('valencia.geojson', encoding='utf-8') as f:
            geojson_data = json.load(f)
        
        # Limpiar nombres en el GeoJSON para que coincidan con los de airbnb y el histórico
        for feature in geojson_data['features']:
            feature['properties']['nombre_limpio'] = clean_text(feature['properties']['nombre'])

        # Pasamos a fechas para compararlo con los historicos
        df_reviews['date'] = pd.to_datetime(df_reviews['date'])
        # Agrupamos los reviews por id de airbnb y obtenemos la fecha mínima (primera review) para cada listing
        # Utilizamos este dato para asumir cuando empezó a operar el airbnb
        df_inicio = df_reviews.groupby('listing_id')['date'].min().reset_index()
        df_inicio.columns = ['id', 'fecha_inicio']
        # Hacemos un merge entre el dataframe de lista de airbnb y el dataframe de reviews (fecha de inicio y id)
        # para poner establecer la fecha en que empezó a operar el airbnb
        df_airbnb = pd.merge(df_airbnb, df_inicio, on='id', how='left')
        df_airbnb['year_start'] = df_airbnb['fecha_inicio'].dt.year

        years = [2016, 2018, 2020, 2022, 2024]
        # Como los precios estan por años en columna, hacemos un melt
        # el melt es una función de pandas que transforma un dataframe de formato ancho a formato largo,
        # es decir, convierte columnas en filas. Para que asi podemos tener 
        # una fila por cada distrito y año, con su precio correspondiente.
        df_precios = df_historico.melt(id_vars=['Distrito'], value_vars=[str(a) for a in years], 
                                      var_name='Año', value_name='Precio_m2')
        df_precios['Año'] = df_precios['Año'].astype(int)
        df_precios['key'] = df_precios['Distrito'].apply(clean_text)

        frames = []
        for y in years:
            # Para cada año, filtramos los airbnb que empezaron a operar ese año o antes,
            # y contamos cuantos hay por distrito.
            airbnb = df_airbnb[df_airbnb['year_start'] <= y].copy()
            count = airbnb.groupby('neighbourhood_group')['id'].count().reset_index()
            count.columns = ['Distrito_NB', 'Total_Airbnb']
            count['key'] = count['Distrito_NB'].apply(clean_text)
            temp = pd.merge(df_precios[df_precios['Año'] == y], count, on='key', how='left').fillna(0)
            frames.append(temp)

        df_final = pd.concat(frames).sort_values(['Distrito', 'Año'])
        return df_final, geojson_data
    except Exception as e:
        st.error(f"Error cargando archivos: {e}")
        return None, None

df_final, geojson_data = cargar_datos()

if df_final is not None:
    # Definimos la interfaz de usuario
    st.title("🏙️ Impacto de Airbnb en Valencia")
    st.markdown("Análisis de la relación entre el crecimiento de pisos turísticos y el precio del alquiler.")

    # Sidebar para filtros. Podremos elegir que distritos queremos ver.
    st.sidebar.header("Filtros")
    selected_Districts = st.sidebar.multiselect(
        "Seleccionar Distritos para el gráfico de líneas:",
        options=df_final['Distrito'].unique(),
        default=df_final.groupby('Distrito').apply(lambda x: (x.iloc[-1]['Precio_m2'] - x.iloc[0]['Precio_m2'])/x.iloc[0]['Precio_m2']).nlargest(3).index.tolist()
    )

    # Un resumen de metricas clave (solo tenemos hasta 2024)
    col1, col2, col3 = st.columns(3)
    avg_price = df_final[df_final['Año'] == 2024]['Precio_m2'].mean()
    total_airbnb = df_final[df_final['Año'] == 2024]['Total_Airbnb'].sum()

    col1.metric("Precio Medio 2024", f"{avg_price:.2f} €/m²")
    col2.metric("Total Airbnb 2024", f"{int(total_airbnb)} listings")
    col3.metric("Año del estudio", "2016 - 2024")

    # -------------------------------------------------------------
    # INSIGHTS RÁPIDOS: TOP HOTSPOTS
    # -------------------------------------------------------------
    st.markdown("### 💡 Insights Rápidos: Top Hotspots")
    
    df_2016 = df_final[df_final['Año'] == 2016].set_index('Distrito')
    df_2024 = df_final[df_final['Año'] == 2024].set_index('Distrito')
    
    # 1. Barrio más saturado (mayor crecimiento absoluto de Airbnb)
    airbnb_growth = df_2024['Total_Airbnb'] - df_2016['Total_Airbnb']
    max_airbnb_district = airbnb_growth.idxmax()
    max_airbnb_growth = airbnb_growth.max()
    
    # 2. Mayor rentabilidad (mayor crecimiento porcentual de precio)
    precio_pct_growth = ((df_2024['Precio_m2'] - df_2016['Precio_m2']) / df_2016['Precio_m2']) * 100
    max_price_growth_district = precio_pct_growth.idxmax()
    max_price_growth_val = precio_pct_growth.max()

    # 3. Rentabilidad con baja saturación (Efecto desplazamiento)
    # Buscamos el distrito que más ha subido de precio pero cuyo crecimiento de Airbnb está por debajo de la mediana
    airbnb_pct_growth = ((df_2024['Total_Airbnb'] - df_2016['Total_Airbnb']) / df_2016['Total_Airbnb'].replace(0, 1)) * 100
    median_airbnb_growth = airbnb_pct_growth.median()
    low_airbnb_districts = airbnb_pct_growth[airbnb_pct_growth < median_airbnb_growth].index
    
    if len(low_airbnb_districts) > 0:
        rentable_district = precio_pct_growth[low_airbnb_districts].idxmax()
        rentable_val = precio_pct_growth[rentable_district]
    else:
        rentable_district = max_price_growth_district
        rentable_val = max_price_growth_val

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Barrio más saturado (Crecimiento Airbnb)", f"{max_airbnb_district}", f"+{int(max_airbnb_growth)} pisos desde 2016", delta_color="inverse")
    col_b.metric("Mayor aumento de precio", f"{max_price_growth_district}", f"+{max_price_growth_val:.1f}% desde 2016", delta_color="inverse")
    col_c.metric("Mayor rentabilidad (Baja saturación Airbnb)", f"{rentable_district}", f"+{rentable_val:.1f}% de precio", delta_color="inverse")
    st.markdown("---")


    # Gráfico de mapa de calor y gráfico de líneas en distintos tabs
    tab1, tab2 = st.tabs(["🗺️ Mapa de Calor", "📈 Evolución Temporal"])
    with tab1:
        st.subheader("Distribución Geográfica de Precios")
        # choropleth_map es una función de plotly para crear mapas coloreados segun valores.
        fig_mapa = px.choropleth_map(
            df_final, geojson=geojson_data, locations="key", featureidkey="properties.nombre_limpio",
            color="Precio_m2", animation_frame="Año", hover_name="Distrito",
            hover_data={"Total_Airbnb": True, "Precio_m2": ':.2f', "key": False},
            color_continuous_scale="Reds", range_color=[df_final['Precio_m2'].min(), df_final['Precio_m2'].max()],
            map_style="carto-positron", zoom=11.5, center={"lat": 39.47, "lon": -0.376}, 
            opacity=0.7, height=600
        )
        # Es la funcion de streamlit para mostrar el grafico, con width stretch para que ocupe todo el ancho disponible.
        st.plotly_chart(fig_mapa, width='stretch')

    with tab2:
        st.subheader("Relación Oferta Airbnb vs Precio Alquiler")
        df_filtrado = df_final[df_final['Distrito'].isin(selected_Districts)]
        # Aqui utilizamos un grafico de lineas para mostrar como crece el precio con el aumento de airbnb
        fig_lineas = px.line(
            df_filtrado, x="Total_Airbnb", y="Precio_m2", color="Distrito",
            markers=True, text="Año",
            labels={"Total_Airbnb": "Cantidad de Airbnb", "Precio_m2": "Precio (€/m²)"},
            height=600
        )
        fig_lineas.update_traces(textposition="top center")
        fig_lineas.update_layout(template="plotly_white")
        st.plotly_chart(fig_lineas, width='stretch')

    # Podemos ver una tabla con los datos finales.
    if st.checkbox("Mostrar tabla de datos"):
        st.dataframe(df_final)