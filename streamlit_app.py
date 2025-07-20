import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd
from datetime import datetime, timedelta
from main import AssistantNavigation, PredicteurSaturation, CollecteurDonnees
import os
from dotenv import load_dotenv
from geopy.geocoders import Nominatim
import time

load_dotenv()

# Configuration de la page
st.set_page_config(
    page_title="🚗 Assistant Parking Paris",
    page_icon="🅿️",
    layout="wide"
)

# Titre principal
st.title("🚗 Assistant Intelligent de Parking - Paris")
st.markdown("Trouvez la meilleure place de parking avec prédiction de la saturation, évitement des travaux et informations métro")

# Initialiser le système
@st.cache_resource
def init_system():
    load_dotenv()
    collecteur = CollecteurDonnees()
    predicteur = PredicteurSaturation(collecteur)
    return AssistantNavigation(predicteur, collecteur)

# Initialiser le géocodeur
@st.cache_resource
def init_geocoder():
    return Nominatim(user_agent="parking-paris-app")

systeme = init_system()
geolocator = init_geocoder()

# Fonction pour géocoder une adresse
def geocode_address(address):
    """Convertit une adresse en coordonnées GPS"""
    try:
        if "paris" not in address.lower():
            address += ", Paris, France"
        
        location = geolocator.geocode(address)
        if location:
            return (location.latitude, location.longitude), location.address
        else:
            return None, None
    except Exception as e:
        st.error(f"Erreur de géocodage avec Nominatim: {e}")
        return None, None

# Interface principale
st.markdown("---")

# Section de saisie des adresses
col1, col2 = st.columns(2)

with col1:
    st.subheader("📍 Point de départ")
    adresse_depart = st.text_input(
        "Entrez votre adresse de départ",
        placeholder="Ex: 10 rue de Rivoli, Paris",
        help="Entrez une adresse complète avec numéro et nom de rue"
    )

with col2:
    st.subheader("🎯 Destination")
    adresse_destination = st.text_input(
        "Entrez votre destination",
        placeholder="Ex: 25 avenue des Champs-Élysées, Paris",
        help="Entrez une adresse complète avec numéro et nom de rue"
    )

# Options avancées
with st.expander("⚙️ Options avancées"):
    col_opt1, col_opt2 = st.columns(2)
    with col_opt1:
        eviter_travaux = st.checkbox("🚧 Éviter les zones de travaux", value=True, help="Privilégier les itinéraires évitant les chantiers")
        afficher_travaux = st.checkbox("👁️ Afficher tous les travaux sur la carte", value=True)
        afficher_metro = st.checkbox("🚇 Afficher les stations de métro", value=True, help="Voir les stations proches et leurs incidents")
    with col_opt2:
        niveau_detail = st.selectbox(
            "📊 Niveau de détail des travaux",
            ["Tous les travaux", "Très perturbants seulement", "Perturbants et plus"],
            index=2
        )
        rayon_metro = st.slider("🔍 Rayon de recherche métro (km)", 0.3, 1.5, 0.8, 0.1, 
                               help="Distance maximale pour chercher les stations de métro")
        

# Nouvelle section pour véhicules électriques
with st.expander("🔋 Options véhicule électrique"):
    col_elec1, col_elec2 = st.columns(2)
    with col_elec1:
        vehicule_electrique = st.checkbox("🚗⚡ Véhicule électrique", value=False, 
                                        help="Afficher les bornes de recharge Belib")
        if vehicule_electrique:
            type_vehicule = st.selectbox(
                "Type de véhicule",
                ["voiture", "utilitaire", "moto"],
                help="Détermine les types de connecteurs compatibles"
            )
    with col_elec2:
        if vehicule_electrique:
            afficher_bornes = st.checkbox("👁️ Afficher les bornes sur la carte", value=True)
            rayon_bornes = st.slider("🔍 Rayon recherche bornes (km)", 0.5, 3.0, 2.0, 0.5)
        else:
            afficher_bornes = False
            rayon_bornes = 2.0
            type_vehicule = "voiture"

# Exemples d'adresses
with st.expander("💡 Exemples d'adresses"):
    ex_col1, ex_col2 = st.columns(2)
    with ex_col1:
        st.markdown("""
        **Points de départ suggérés:**
        - Place du Châtelet, Paris
        - 1 Avenue de l'Opéra, Paris
        - Gare du Nord, Paris
        - 50 Boulevard Saint-Michel, Paris
        """)
    with ex_col2:
        st.markdown("""
        **Destinations suggérées:**
        - Musée du Louvre, Paris
        - Tour Eiffel, Paris
        - 140 Rue de Rivoli, Paris
        - Cathédrale Notre-Dame, Paris
        """)

# Bouton de recherche centré
col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
with col_btn2:
    rechercher = st.button(
        "🔍 Rechercher un parking",
        type="primary",
        use_container_width=True,
        disabled=(not adresse_depart or not adresse_destination)
    )

# Ligne de séparation
st.markdown("---")

# Zone de résultats
if rechercher and adresse_depart and adresse_destination:
    with st.container():
        # Géolocalisation
        with st.spinner("🔄 Géolocalisation des adresses..."):
            coords_depart, adresse_complete_depart = geocode_address(adresse_depart)
            coords_destination, adresse_complete_destination = geocode_address(adresse_destination)
        
        if coords_depart and coords_destination:
            # Confirmation des adresses
            st.success("✅ Adresses trouvées avec succès!")
            
            # Afficher les adresses géocodées
            info_col1, info_col2 = st.columns(2)
            with info_col1:
                st.info(f"**Départ:** {adresse_complete_depart}")
            with info_col2:
                st.info(f"**Destination:** {adresse_complete_destination}")
            
            # Recherche de parking
            with st.spinner("🔍 Recherche des meilleurs parkings, analyse des travaux et vérification du métro..."):
                if vehicule_electrique:
                    resultat = systeme.recommander_avec_bornes_electriques(
                        coords_depart, coords_destination, datetime.now(),
                        type_vehicule=type_vehicule, inclure_bornes=True
                        )
                else:
                    resultat = systeme.assister_conducteur(coords_depart, coords_destination)

            
            # Affichage des résultats
            st.markdown("## 📊 Parking Recommandé")
            
            if resultat and resultat.get('parking_recommande'):
                # Alertes prioritaires
                alertes_importantes = []
                
                # Alertes travaux
                if resultat.get('travaux_sur_trajet'):
                    travaux_impactants = resultat['travaux_sur_trajet']
                    if any(t.niveau_perturbation == "Très perturbant" for t in travaux_impactants):
                        alertes_importantes.append(("error", f"⚠️ **Attention:** {len(travaux_impactants)} travaux très perturbants détectés sur votre trajet !"))
                    else:
                        alertes_importantes.append(("warning", f"🚧 **Info:** {len(travaux_impactants)} travaux détectés sur votre trajet"))
                
                # Alertes métro
                if resultat.get('impact_metro'):
                    impact_metro = resultat['impact_metro']
                    if impact_metro['stations_fermees_destination']:
                        nb_stations = len(impact_metro['stations_fermees_destination'])
                        alertes_importantes.append(("success", f"✅ **Avantage:** {nb_stations} station(s) fermée(s) près de votre destination - parking plus attractif !"))
                    elif impact_metro['stations_fermees_parking']:
                        nb_stations = len(impact_metro['stations_fermees_parking'])
                        alertes_importantes.append(("info", f"ℹ️ **Info:** {nb_stations} station(s) fermée(s) près du parking"))
                
                # Afficher les alertes
                for type_alerte, message in alertes_importantes:
                    if type_alerte == "error":
                        st.error(message)
                    elif type_alerte == "warning":
                        st.warning(message)
                    elif type_alerte == "success":
                        st.success(message)
                    else:
                        st.info(message)
                
                # Container pour les métriques
                metrics_container = st.container()
                with metrics_container:
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        st.metric(
                            label="⏱️ Temps total",
                            value=f"{resultat['temps_estime']['total']} min",
                            delta=f"Parking: {resultat['temps_estime']['acces_parking']}min"
                        )
                    
                    with col2:
                        st.metric(
                            label="🚗 Places disponibles",
                            value=f"{resultat['parking_recommande']['places_disponibles']}",
                            delta=f"sur {resultat['parking_recommande']['capacite_totale']}"
                        )
                    
                    with col3:
                        st.metric(
                            label="💰 Tarif horaire",
                            value=f"{resultat['parking_recommande']['tarif_horaire']}€"
                        )
                    
                    with col4:
                        saturation_actuelle = float(resultat['saturation']['actuelle'])
                        saturation_predite = float(resultat['saturation']['predite'])
                        
                        # Calculer la vraie différence
                        difference = saturation_predite - saturation_actuelle
                        difference_pct = difference * 100
                        
                        # Formater le delta correctement
                        if difference > 0:
                            delta_text = f"+{difference_pct:.0f}% (plus saturé)"
                            delta_color = "inverse"
                        elif difference < 0:
                            delta_text = f"{difference_pct:.0f}% (moins saturé)" 
                            delta_color = "normal"
                        else:
                            delta_text = "Stable"
                            delta_color = "off"
                        
                        st.metric(
                            label="📊 Saturation",
                            value=f"{saturation_actuelle*100:.0f}%",
                            delta=delta_text,
                            delta_color=delta_color
                        )
                # Métriques bornes électriques si applicable
                if vehicule_electrique and resultat.get('bornes_electriques'):
                    bornes_info = resultat['bornes_electriques']
                    st.markdown("### 🔋 Bornes électriques proches")
                    
                    col_b1, col_b2, col_b3, col_b4 = st.columns(4)
                    with col_b1:
                        st.metric("Total bornes", bornes_info['total_trouvees'])
                    with col_b2:
                        st.metric("Compatibles", bornes_info['compatibles'])
                    with col_b3:
                        st.metric("Disponibles", bornes_info['disponibles'])
                    with col_b4:
                        vehicule_emoji = {"voiture": "🚗", "utilitaire": "🚐", "moto": "🏍️"}.get(type_vehicule, "🚗")
                        st.metric("Type véhicule", f"{vehicule_emoji} {type_vehicule.title()}")

                # Informations détaillées
                st.markdown("### 📋 Détails")
                
                detail_col1, detail_col2 = st.columns([2, 1])
                
                with detail_col1:
                    with st.container():
                        # Informations sur les perturbations
                        perturbations_info = ""
                        if resultat.get('travaux_sur_trajet'):
                            nb_travaux = len(resultat['travaux_sur_trajet'])
                            perturbations_info += f"<p style='color: #e74c3c;'><b>🚧 Travaux sur trajet:</b> {nb_travaux} chantier(s) détecté(s)</p>"
                        
                        if resultat.get('impact_metro', {}).get('recommandation'):
                            metro_reco = resultat['impact_metro']['recommandation']
                            color = "#27ae60" if "avantageux" in metro_reco else "#3498db"
                            perturbations_info += f"<p style='color: {color};'><b>🚇 Métro:</b> {metro_reco}</p>"
                        
                        st.markdown(f"""
                        <div style='background-color: #f0f8ff; padding: 20px; border-radius: 10px; border: 1px solid #4169e1;'>
                            <h4 style='color: #1e3a8a;'>{resultat['parking_recommande']['nom']}</h4>
                            <p style='color: #334155;'><b>📍 Adresse:</b> {resultat['parking_recommande']['adresse']}</p>
                            <p style='color: #334155;'><b>🚗 Trajet en voiture:</b> {resultat['temps_estime']['acces_parking']} minutes</p>
                            <p style='color: #334155;'><b>🚶 Marche à pied:</b> {resultat['temps_estime']['marche_destination']} minutes</p>
                            {perturbations_info}
                        </div>
                        """, unsafe_allow_html=True)
                
                with detail_col2:
                    saturation_float = float(resultat['saturation']['actuelle']) 
                    if saturation_float < 0.50:
                        color = "#28a745"
                        status = "Peu fréquenté"
                    elif saturation_float < 0.80:
                        color = "#ffc107"
                        status = "Moyennement fréquenté"
                    else:
                        color = "#dc3545"
                        status = "Très fréquenté"
                    
                    st.markdown(f"""
                    <div style='background-color: {color}20; padding: 20px; border-radius: 10px; border: 2px solid {color}; text-align: center;'>
                        <h4 style='color: {color};'>État actuel</h4>
                        <h2 style='color: {color};'>{status}</h2>
                        <p style='color: #334155;'>{saturation_float*100:.0f}% occupé</p>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Carte interactive avec travaux et métro
                st.markdown("### 🗺️ Carte Interactive")
                parking_lat = resultat['parking_recommande']['latitude']
                parking_lon = resultat['parking_recommande']['longitude']
                if parking_lat is not None and parking_lon is not None:
                    # Créer la carte
                    m = folium.Map(
                        location=[parking_lat, parking_lon],
                        zoom_start=13,
                        tiles='OpenStreetMap'
                    )
                    
                    # Marqueur de départ (bleu)
                    folium.Marker(
                        coords_depart,
                        popup="<b>Point de départ</b>",
                        tooltip="Départ",
                        icon=folium.Icon(color='blue', icon='home', prefix='fa')
                    ).add_to(m)
                    
                    # Marqueur de destination (rouge)
                    folium.Marker(
                        coords_destination,
                        popup="<b>Destination finale</b>",
                        tooltip="Destination",
                        icon=folium.Icon(color='red', icon='flag', prefix='fa')
                    ).add_to(m)
                    
                    # Marqueur du parking (vert)
                    folium.Marker(
                        [parking_lat, parking_lon],
                        popup=f"<b>{resultat['parking_recommande']['nom']}</b><br>Places: {resultat['parking_recommande']['places_disponibles']}/{resultat['parking_recommande']['capacite_totale']}",
                        tooltip="Parking recommandé",
                        icon=folium.Icon(color='green', icon='car', prefix='fa')
                    ).add_to(m)

                    # Ajouter les bornes électriques à la carte
                if vehicule_electrique and afficher_bornes and resultat.get('bornes_electriques'):
                    bornes_recommandees = resultat['bornes_electriques']['recommandees']
                    
                    for i, borne_data in enumerate(bornes_recommandees):
                        borne = borne_data['borne']
                        
                        # Couleur selon statut et disponibilité
                        if not borne.compatible_vehicule:
                            icon_color = 'gray'
                            icon_symbol = 'times'
                        elif not borne.disponible or borne.statut != "En service":
                            icon_color = 'red'
                            icon_symbol = 'bolt'
                        elif borne.nb_places_libres == 0:
                            icon_color = 'orange'
                            icon_symbol = 'bolt'
                        else:
                            icon_color = 'lightgreen'
                            icon_symbol = 'bolt'
                        
                        # Popup détaillé
                        connecteurs_str = ", ".join(borne.types_connecteurs)
                        popup_html = f"""
                        <div style='width: 250px;'>
                            <h4 style='color: #27ae60;'>🔋 {borne.nom}</h4>
                            <p><b>📍 Adresse:</b> {borne.adresse}</p>
                            <p><b>⚡ Puissance:</b> {borne.puissance_max}</p>
                            <p><b>🔌 Connecteurs:</b> {connecteurs_str}</p>
                            <p><b>📊 Points de charge:</b> {borne.nb_points_charge}</p>
                            <p><b>🟢 Libres:</b> {borne.nb_places_libres}/{borne.nb_points_charge}</p>
                            <p><b>🏢 Opérateur:</b> {borne.operateur}</p>
                            <p><b>💰 Tarif:</b> {borne.tarif_info}</p>
                            <p><b>🚶 Marche destination:</b> {borne_data['temps_marche_destination']} min</p>
                            <p><b>📏 Distance:</b> {borne.distance_point:.2f} km</p>
                            <p><b>✅ Compatible:</b> {'Oui' if borne.compatible_vehicule else 'Non'}</p>
                            <p><b>📋 Statut:</b> {borne.statut}</p>
                        </div>
                        """
                        
                        # Rang dans les recommandations
                        rank_text = f"#{i+1}" if i < 3 else ""
                        
                        folium.Marker(
                            [borne.latitude, borne.longitude],
                            popup=folium.Popup(popup_html, max_width=300),
                            tooltip=f"🔋 {borne.nom} {rank_text}",
                            icon=folium.Icon(color=icon_color, icon=icon_symbol, prefix='fa')
                        ).add_to(m)

                    
                    # Afficher les travaux sur la carte
                    if afficher_travaux and resultat.get('travaux_tous'):
                        for travail in resultat['travaux_tous']:
                            # Filtrer selon le niveau de détail choisi
                            if niveau_detail == "Très perturbants seulement" and travail.niveau_perturbation != "Très perturbant":
                                continue
                            elif niveau_detail == "Perturbants et plus" and travail.niveau_perturbation not in ["Perturbant", "Très perturbant"]:
                                continue
                            
                            # Couleur selon le niveau de perturbation
                            if travail.niveau_perturbation == "Très perturbant":
                                icon_color = "darkred"
                                icon_symbol = "exclamation-triangle"
                            else:
                                icon_color = "orange"
                                icon_symbol = "wrench"
                            
                            # Popup avec informations détaillées
                            popup_html = f"""
                            <div style='width: 200px;'>
                                <h4 style='color: #e74c3c;'>🚧 {travail.nom}</h4>
                                <p><b>Type:</b> {travail.niveau_perturbation}</p>
                                <p><b>Statut:</b> {travail.statut}</p>
                                <p><b>Description:</b> {travail.description[:100]}...</p>
                                <p><b>Fin prévue:</b> {travail.date_fin.strftime('%d/%m/%Y')}</p>
                            </div>
                            """
                            
                            # Ajouter le marqueur de travaux
                            folium.Marker(
                                [travail.latitude, travail.longitude],
                                popup=folium.Popup(popup_html, max_width=250),
                                tooltip=f"🚧 {travail.nom}",
                                icon=folium.Icon(color=icon_color, icon=icon_symbol, prefix='fa')
                            ).add_to(m)
                            
                            # Ajouter le polygone si disponible
                            if travail.geometrie and len(travail.geometrie) > 2:
                                folium.Polygon(
                                    locations=travail.geometrie,
                                    color='red' if travail.niveau_perturbation == "Très perturbant" else 'orange',
                                    fillColor='red' if travail.niveau_perturbation == "Très perturbant" else 'orange',
                                    fillOpacity=0.3,
                                    weight=2,
                                    popup=f"Zone de travaux: {travail.nom}"
                                ).add_to(m)
                    
                    # Afficher les stations de métro
                    if afficher_metro:
                        # Stations près de la destination
                        if resultat.get('stations_destination'):
                            for station in resultat['stations_destination']:
                                # Couleur selon l'état
                                if station.fermee:
                                    icon_color = "red"
                                    icon_symbol = "times-circle"
                                    status_text = f"FERMÉE - {station.raison_fermeture}"
                                else:
                                    icon_color = "blue"
                                    icon_symbol = "subway"
                                    status_text = "Ouverte"
                                
                                popup_html = f"""
                                <div style='width: 200px;'>
                                    <h4 style='color: #2980b9;'>🚇 {station.nom}</h4>
                                    <p><b>Lignes:</b> {', '.join(station.lignes)}</p>
                                    <p><b>Statut:</b> {status_text}</p>
                                    <p><b>Zone:</b> Près de la destination</p>
                                </div>
                                """
                                
                                folium.Marker(
                                    [station.latitude, station.longitude],
                                    popup=folium.Popup(popup_html, max_width=250),
                                    tooltip=f"🚇 {station.nom}",
                                    icon=folium.Icon(color=icon_color, icon=icon_symbol, prefix='fa')
                                ).add_to(m)
                        
                        # Stations près du parking
                        if resultat.get('stations_parking'):
                            for station in resultat['stations_parking']:
                                # Couleur selon l'état (différente pour distinguer)
                                if station.fermee:
                                    icon_color = "darkred"
                                    icon_symbol = "times-circle"
                                    status_text = f"FERMÉE - {station.raison_fermeture}"
                                else:
                                    icon_color = "lightblue"
                                    icon_symbol = "subway"
                                    status_text = "Ouverte"
                                
                                popup_html = f"""
                                <div style='width: 200px;'>
                                    <h4 style='color: #3498db;'>🚇 {station.nom}</h4>
                                    <p><b>Lignes:</b> {', '.join(station.lignes)}</p>
                                    <p><b>Statut:</b> {status_text}</p>
                                    <p><b>Zone:</b> Près du parking</p>
                                </div>
                                """
                                
                                folium.Marker(
                                    [station.latitude, station.longitude],
                                    popup=folium.Popup(popup_html, max_width=250),
                                    tooltip=f"🚇 {station.nom}",
                                    icon=folium.Icon(color=icon_color, icon=icon_symbol, prefix='fa')
                                ).add_to(m)
                    
                # Section détaillée des bornes électriques
                        if vehicule_electrique and resultat.get('bornes_electriques'):
                            st.markdown("### 🔋 Bornes électriques recommandées")
                            
                            bornes_info = resultat['bornes_electriques']
                            
                            # Alertes bornes
                            if bornes_info['compatibles'] == 0:
                                st.error("❌ Aucune borne compatible trouvée pour votre type de véhicule")
                            elif bornes_info['disponibles'] == 0:
                                st.warning("⚠️ Aucune borne disponible actuellement")
                            elif bornes_info['disponibles'] < 3:
                                st.info(f"ℹ️ Seulement {bornes_info['disponibles']} borne(s) disponible(s)")
                            
                            # Tableau des bornes recommandées
                            if bornes_info['recommandees']:
                                bornes_data = []
                                for i, borne_data in enumerate(bornes_info['recommandees']):
                                    borne = borne_data['borne']
                                    
                                    # Emojis de statut
                                    statut_emoji = "🟢" if borne.disponible and borne.statut == "En service" else "🔴"
                                    compat_emoji = "✅" if borne.compatible_vehicule else "❌"
                                    
                                    # Type de charge
                                    if "50 kW" in borne.puissance_max or "DC" in borne.puissance_max:
                                        charge_type = "🚀 Rapide"
                                    elif "22 kW" in borne.puissance_max:
                                        charge_type = "⚡ Standard"
                                    else:
                                        charge_type = "🐌 Lente"
                                    
                                    bornes_data.append({
                                        "Rang": f"#{i+1}",
                                        "Borne": borne.nom,
                                        "📍 Distance": f"{borne.distance_point:.2f} km",
                                        "⚡ Puissance": f"{charge_type} {borne.puissance_max}",
                                        "🔌 Connecteurs": ", ".join(borne.types_connecteurs[:2]),  # Limiter l'affichage
                                        f"📊 Libres": f"{borne.nb_places_libres}/{borne.nb_points_charge}",
                                        "🚶 Marche": f"{borne_data['temps_marche_destination']} min",
                                        "✅ Compatible": compat_emoji,
                                        "📋 Statut": f"{statut_emoji} {borne.statut}",
                                        "💰 Tarif": borne.tarif_info
                                    })
                                
                                df_bornes = pd.DataFrame(bornes_data)
                                st.dataframe(df_bornes, use_container_width=True, hide_index=True)
                                
                                # Conseils d'utilisation
                                st.markdown("#### 💡 Conseils")
                                conseils = []
                                
                                # Analyser les bornes pour donner des conseils
                                bornes_rapides = [b for b in bornes_info['recommandees'] if "50 kW" in b['borne'].puissance_max]
                                bornes_proches = [b for b in bornes_info['recommandees'] if b['distance_destination'] < 0.5]
                                
                                if bornes_rapides:
                                    conseils.append("🚀 Des bornes de charge rapide sont disponibles pour un rechargement express")
                                
                                if bornes_proches:
                                    conseils.append("🎯 Des bornes sont très proches de votre destination (< 500m)")
                                
                                if any(b['borne'].acces != "Public" for b in bornes_info['recommandees']):
                                    conseils.append("⚠️ Certaines bornes peuvent avoir un accès restreint - vérifiez avant de vous déplacer")
                                
                                connecteurs_vehicule = {"voiture": "Type 2 ou Combo CCS", "utilitaire": "Type 2", "moto": "Type EF ou Type 2"}
                                conseil_connecteur = connecteurs_vehicule.get(type_vehicule, "Type 2")
                                conseils.append(f"🔌 Votre {type_vehicule} est généralement compatible avec: {conseil_connecteur}")
                                
                                for conseil in conseils:
                                    st.info(conseil)

                    # Tracer les trajets
                    if resultat.get('route_to_parking_points') and len(resultat['route_to_parking_points']) > 1:
                        # Trajet vers parking avec style adapté aux travaux
                        line_color = 'darkblue' if not resultat.get('travaux_sur_trajet') else 'purple'
                        line_weight = 5 if not resultat.get('travaux_sur_trajet') else 6
                        
                        folium.PolyLine(
                            locations=resultat['route_to_parking_points'],
                            color=line_color,
                            weight=line_weight,
                            opacity=0.8,
                            tooltip="Trajet en voiture (optimisé pour éviter les travaux)" if eviter_travaux else "Trajet en voiture"
                        ).add_to(m)
                    
                    # Trajet de marche
                    if resultat.get('route_parking_to_dest_points') and len(resultat['route_parking_to_dest_points']) > 1:
                        folium.PolyLine(
                            locations=resultat['route_parking_to_dest_points'],
                            color='green',
                            weight=3,
                            opacity=0.8,
                            dash_array='5, 5',
                            tooltip="Marche jusqu'à destination"
                        ).add_to(m)

                    # Ajuster la vue
                    all_points_for_bounds = [coords_depart, coords_destination, [parking_lat, parking_lon]]
                    
                    if resultat.get('route_to_parking_points'):
                        all_points_for_bounds.extend(resultat['route_to_parking_points'])
                    if resultat.get('route_parking_to_dest_points'):
                        all_points_for_bounds.extend(resultat['route_parking_to_dest_points'])

                    valid_points = [p for p in all_points_for_bounds if p is not None and isinstance(p, (list, tuple)) and len(p) == 2]

                    if valid_points:
                        m.fit_bounds(valid_points)
                    
                    # Afficher la carte
                    st_folium(m, width=None, height=600, returned_objects=[])
                else:
                    st.warning("Impossible d'afficher la carte : Coordonnées du parking introuvables.")
                
                # Informations détaillées sur le métro
                if resultat.get('incidents_metro') and any(inc.impact_niveau != 'normal' for inc in resultat['incidents_metro']):
                    st.markdown("### 🚇 État du réseau métro")
                    
                    # Filtrer les incidents significatifs
                    incidents_notables = [inc for inc in resultat['incidents_metro'] if inc.impact_niveau != 'normal']
                    
                    if incidents_notables:
                        metro_col1, metro_col2 = st.columns(2)
                        
                        with metro_col1:
                            st.markdown("**Lignes avec perturbations:**")
                            for incident in incidents_notables:
                                if incident.impact_niveau == "interrompu":
                                    st.error(f"🚫 Ligne {incident.ligne}: {incident.titre}")
                                elif incident.impact_niveau == "perturbe":
                                    st.warning(f"⚠️ Ligne {incident.ligne}: {incident.titre}")
                                else:
                                    st.info(f"🔧 Ligne {incident.ligne}: {incident.titre}")
                                
                                st.caption(incident.message)
                        
                        with metro_col2:
                            # Résumé des impacts
                            lignes_perturbees = len([inc for inc in incidents_notables if inc.impact_niveau == "perturbe"])
                            lignes_interrompues = len([inc for inc in incidents_notables if inc.impact_niveau == "interrompu"])
                            lignes_travaux = len([inc for inc in incidents_notables if inc.impact_niveau == "travaux"])
                            
                            st.metric("Lignes perturbées", lignes_perturbees)
                            st.metric("Lignes interrompues", lignes_interrompues)
                            st.metric("Lignes en travaux", lignes_travaux)
                
                # Parkings alternatifs avec informations complètes
                if resultat['alternatives']:
                    st.markdown("### 🔄 Autres parkings disponibles")
                    
                    # Préparer les données avec informations complètes
                    alternatives_data = []
                    for alt in resultat['alternatives']:
                        travaux_col = "🟢 Aucun" if alt['nb_travaux_impactants'] == 0 else f"🚧 {alt['nb_travaux_impactants']} travaux"
                        
                        metro_col = "➖ Normal"
                        if alt.get('impact_metro'):
                            recommandation = str(alt['impact_metro'].get('recommandation', '') or '').lower()
                            if "avantageux" in recommandation:
                                metro_col = "✅ Avantageux"
                            elif "attention" in recommandation:
                                metro_col = "⚠️ Attention"
                        
                        alternatives_data.append({
                            "Parking": alt['nom'],
                            "⏱️ Temps total": f"{alt['temps_total']} min",
                            "📊 Saturation prévue": f"{alt['saturation_predite']*100:.0f}%",
                            "🚧 Travaux": travaux_col,
                            "🚇 Impact métro": metro_col,
                            "🎯 Fiabilité": f"{alt['fiabilite_prediction']*100:.0f}%"
                        })
                    
                    df_alt = pd.DataFrame(alternatives_data)
                    st.dataframe(df_alt, use_container_width=True, hide_index=True)
                
                # Résumé global des perturbations
                st.markdown("### 📊 Résumé des conditions de circulation")
                
                summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
                
                with summary_col1:
                    total_travaux = len(resultat.get('travaux_tous', []))
                    st.metric("Total travaux détectés", total_travaux)
                
                with summary_col2:
                    travaux_sur_trajet = len(resultat.get('travaux_sur_trajet', []))
                    st.metric("Travaux sur votre trajet", travaux_sur_trajet)
                
                with summary_col3:
                    incidents_notables = len([inc for inc in resultat.get('incidents_metro', []) if inc.impact_niveau != 'normal'])
                    st.metric("Lignes métro perturbées", incidents_notables)
                
                with summary_col4:
                    stations_fermees_total = 0
                    if resultat.get('impact_metro'):
                        stations_fermees_total = len(resultat['impact_metro'].get('stations_fermees_destination', [])) + len(resultat['impact_metro'].get('stations_fermees_parking', []))
                    st.metric("Stations fermées proches", stations_fermees_total)

                if vehicule_electrique and resultat.get('bornes_electriques'):
                    # Ligne supplémentaire pour les bornes
                    summary_col5, summary_col6, summary_col7, summary_col8 = st.columns(4)
                    
                    with summary_col5:
                        st.metric("Bornes trouvées", bornes_info['total_trouvees'])
                    
                    with summary_col6:
                        st.metric("Bornes compatibles", bornes_info['compatibles'])
                    
                    with summary_col7:
                        st.metric("Bornes disponibles", bornes_info['disponibles'])
                    
                    with summary_col8:
                        if bornes_info['recommandees']:
                            plus_proche = min(bornes_info['recommandees'], key=lambda x: x['distance_destination'])
                            st.metric("Plus proche", f"{plus_proche['distance_destination']:.1f} km")
                        else:
                            st.metric("Plus proche", "N/A")
                                
                else:
                    st.info("Aucune recommandation de parking n'a pu être générée pour les adresses spécifiées. Veuillez réessayer.")

        else:
            st.error("""
            ❌ **Impossible de localiser une ou plusieurs adresses.**
            
            Vérifiez que :
            - L'adresse est complète (numéro, rue, ville)
            - L'orthographe est correcte
            - L'adresse existe à Paris
            """)
else:
    st.info("Veuillez entrer vos adresses de départ et de destination pour commencer.")

# Sidebar avec informations
with st.sidebar:
    st.header("ℹ️ Guide d'utilisation")
    
    st.markdown("""
    ### 🎯 Comment utiliser l'application ?
    
    1. **Entrez une adresse de départ**
       - Ex: "42 rue de Rivoli, Paris"
       - Ex: "Gare du Nord"
    
    2. **Entrez votre destination**
       - Ex: "Tour Eiffel"
       - Ex: "1 avenue des Champs-Élysées"
    
    3. **Configurez les options** (facultatif)
       - Évitement des zones de travaux
       - Affichage des chantiers sur la carte
       - Informations stations de métro
    
    4. **Cliquez sur Rechercher**
    
    ### 📊 Comprendre les résultats
    
    - **🔵 Marqueur bleu** = Votre position
    - **🟢 Marqueur vert** = Parking recommandé
    - **🔴 Marqueur rouge** = Destination
    - **🚧 Marqueurs orange/rouge** = Travaux en cours
    - **🚇 Marqueurs bleus** = Stations de métro
    
    - **Ligne bleue/violette** = Trajet en voiture
    - **Ligne verte pointillée** = Marche à pied
    - **Zones colorées** = Emprises de chantiers
    
    ### 🚧 Légende des travaux
    
    - **🚧 Orange** = Travaux perturbants
    - **🚧 Rouge foncé** = Très perturbants
    - **Zone colorée** = Emprise du chantier
    
    ### 🚇 Légende du métro
    
    - **🚇 Bleu** = Station ouverte près destination
    - **🚇 Bleu clair** = Station ouverte près parking
    - **🚇 Rouge** = Station fermée
    - **🟢 Avantageux** = Station fermée = plus de demande parking
    - **⚠️ Attention** = Station fermée près parking
                
    ### 🔋 Véhicules électriques
    
    **Types de véhicules supportés:**
    - **🚗 Voiture** = Type 2, Combo CCS, CHAdeMO
    - **🚐 Utilitaire** = Type 2, Combo CCS  
    - **🏍️ Moto** = Type 2, Type EF
    
    **Légende des bornes:**
    - **🔋 Vert clair** = Disponible et compatible
    - **🔋 Orange** = Occupé mais compatible
    - **🔋 Rouge** = Hors service
    
    ### 💡 Astuces
    
    - Activez l'évitement des travaux pour des trajets optimisés
    - Les fermetures de métro peuvent rendre certains parkings plus attractifs
    - Vérifiez l'état du réseau métro avant de partir
    - Consultez les parkings alternatifs si trop de perturbations
    """)
    
    # Météo actuelle
    st.markdown("### 🌤️ Météo actuelle")
    meteo_coords = (48.8566, 2.3522)
    
    try:
        if 'coords_depart' in locals() and coords_depart:
            meteo_coords = coords_depart

        meteo_data = systeme.collecteur.obtenir_donnees_meteo(meteo_coords[0], meteo_coords[1])
        if meteo_data and not meteo_data.get("error"):
            temp = "N/A"
            condition = "Données météo disponibles"
            
            first_forecast_key = None
            for key in sorted(meteo_data.keys()):
                if key.isdigit() and meteo_data[key] and 'temperature' in meteo_data[key]:
                    first_forecast_key = key
                    break
            
            if first_forecast_key:
                temp_c = meteo_data[first_forecast_key].get('temperature', {}).get('2m')
                if temp_c is not None:
                    temp = f"{temp_c:.1f}"
                    condition = "Prévision météo GFS"
                
                if meteo_data[first_forecast_key].get('precipitation', {}).get('1h_acc', 0) > 0.5:
                    condition += " (Précipitations)"
                
            st.write(f"**Condition:** {condition}")
            st.write(f"Température: {temp}°C")
            st.caption("Données Infoclimat GFS")
        else:
            st.warning(f"Impossible de récupérer les données météo. Vérifiez les clés Infoclimat et la connectivité.")
            if meteo_data and meteo_data.get("error"):
                st.caption(f"Détail: {meteo_data['error']}")
    except Exception as e:
        st.error(f"Erreur lors de l'affichage de la météo: {e}")

# Footer
st.markdown("---")
st.caption("💡 Application complète - Intègre parkings, travaux et métro parisiens en temps réel")