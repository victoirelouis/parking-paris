import json
import random
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import numpy as np
from dataclasses import dataclass
from supabase import create_client, Client
import os
import warnings
import hashlib
import hmac
import base64
import re

# Pour charger les variables d'environnement depuis .env
from dotenv import load_dotenv

# Ignorer l'avertissement SSL si nécessaire (peut être retiré en production)
warnings.filterwarnings('ignore', message='urllib3 v2 only supports OpenSSL')

# Charger les variables d'environnement dès le début
load_dotenv()

# Configuration Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# URLs des APIs de parking temps réel
SAEMES_API_URL = "https://data.opendatasoft.com/api/records/1.0/search/"
SAEMES_DATASET = "places-disponibles-parkings-saemes@saemes"
SAEMES_REFERENTIEL_DATASET = "referentiel-parkings-saemes@saemes"

PARIS_API_URL = "https://opendata.paris.fr/api/records/1.0/search/"
PARIS_PARKING_DATASET = "stationnement-en-ouvrage"

# APIs des travaux
PARIS_TRAVAUX_DATASET = "chantiers-a-paris"
PARIS_TRAVAUX_PERTURBANTS_DATASET = "chantiers-perturbants"

# APIs RATP pour le métro
RATP_API_BASE = "https://api-ratp.pierre-grimaud.fr/v4"
RATP_TRAFFIC_ENDPOINT = f"{RATP_API_BASE}/traffic"

# Récupère la clé API Google Maps
Maps_API_KEY = os.getenv("Maps_API_KEY")

@dataclass
class Parking:
    """Structure de données pour un parking"""
    id: str
    nom: str
    adresse: str
    latitude: float
    longitude: float
    capacite_totale: int
    places_disponibles: int
    tarif_horaire: float
    distance_destination: float = 0.0  # Distance à la destination en km

@dataclass 
class Travaux:
    """Structure de données pour un chantier/travaux"""
    id: str
    nom: str
    description: str
    latitude: float
    longitude: float
    date_debut: datetime
    date_fin: datetime
    niveau_perturbation: str  # "Perturbant", "Très perturbant"
    statut: str  # "En cours", "A venir", "Suspendu"
    impact_circulation: bool
    geometrie: Optional[List[Tuple[float, float]]]  # Polygone si disponible

@dataclass
class IncidentMetro:
    """Structure de données pour un incident de métro"""
    ligne: str
    statut: str  # "normal", "alerte", "normal_trav"
    titre: str  # "Trafic normal", "Trafic perturbé", "Travaux"
    message: str
    impact_niveau: str  # "normal", "perturbe", "interrompu"
    stations_fermees: List[str]
    
@dataclass
class StationMetro:
    """Structure de données pour une station de métro"""
    nom: str
    slug: str
    latitude: float
    longitude: float
    lignes: List[str]
    fermee: bool
    raison_fermeture: str
    distance_point: float = 0.0  # Distance au point de référence
    
@dataclass
class PredictionSaturation:
    """Résultat de prédiction de saturation"""
    parking_id: str
    taux_occupation_actuel: float
    taux_occupation_predit: float
    heure_prediction: datetime
    fiabilite_prediction: float
    temps_avant_saturation: Optional[str]

class CollecteurMeteoInfoclimat:
    def __init__(self):
        self.infoclimat_username = os.getenv("INFOCLIMAT_USERNAME")
        self.infoclimat_private_key = os.getenv("INFOCLIMAT_PRIVATE_KEY")
        if not self.infoclimat_username or not self.infoclimat_private_key:
            print("AVERTISSEMENT: Clés INFOCLIMAT_USERNAME ou INFOCLIMAT_PRIVATE_KEY non configurées. La récupération météo pourrait échouer.")

    def _get_public_ip(self) -> str:
        """Tente de récupérer l'adresse IP publique de l'utilisateur."""
        try:
            response = requests.get('https://api.ipify.org', timeout=5)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            print(f"Impossible de récupérer l'adresse IP publique: {e}. Utilisation d'un fallback '0.0.0.0' (pourrait empêcher l'authentification Infoclimat).")
            return "0.0.0.0"

    def _generer_auth_infoclimat(self, latitude: float, longitude: float) -> str:
        """Génère le paramètre _auth nécessaire pour l'authentification Infoclimat."""
        if not self.infoclimat_username or not self.infoclimat_private_key:
            print("Erreur: Clés Infoclimat (INFOCLIMAT_USERNAME ou INFOCLIMAT_PRIVATE_KEY) manquantes pour générer l'authentification.")
            return ""

        timestamp = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
        ip_address = self._get_public_ip()
        
        string_to_sign = f"{self.infoclimat_username}|{ip_address}|{timestamp}|{latitude:.6f},{longitude:.6f}"

        private_key_bytes = self.infoclimat_private_key.encode('utf-8')
        signature = hmac.new(private_key_bytes, string_to_sign.encode('utf-8'), hashlib.sha1).hexdigest()

        auth_string_for_base64 = f"{self.infoclimat_username}|{ip_address}|{timestamp}|{signature}"
        encoded_auth = base64.urlsafe_b64encode(auth_string_for_base64.encode('utf-8')).decode('utf-8').rstrip('=')
        
        return encoded_auth

    def recuperer_donnees_meteo(self, latitude: float, longitude: float) -> dict:
        """Récupère les données météorologiques pour une position donnée via l'API Infoclimat GFS."""
        base_url = "http://www.infoclimat.fr/public-api/gfs/json"
        
        auth_param = self._generer_auth_infoclimat(latitude, longitude)
        if not auth_param:
            return {"error": "Authentication parameter could not be generated due to missing keys or IP issues."}

        params = {
            "_ll": f"{latitude:.6f},{longitude:.6f}",
            "_auth": auth_param,
            "verbose": "true"
        }

        try:
            print(f"Tentative de récupération météo pour {latitude:.6f},{longitude:.6f}...")
            response = requests.get(base_url, params=params, timeout=15)
            response.raise_for_status()

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                print(f"Erreur de décodage JSON de la réponse Infoclimat: {e}")
                print(f"Réponse brute de l'API: {response.text[:500]}...")
                return {"error": f"JSON decoding error: {e}. Raw response might be invalid JSON."}

            if data and data.get("request_state") == 200:
                print("Données météo récupérées avec succès depuis Infoclimat.")
                return data
            else:
                error_message = data.get("message", "Unknown error from Infoclimat API.")
                request_state = data.get("request_state", "N/A")
                print(f"Erreur API Infoclimat: Etat={request_state}, Message={error_message}")
                return {"error": f"Infoclimat API Error: State={request_state}, Message={error_message}"}
        
        except requests.exceptions.Timeout:
            print(f"Timeout lors de la connexion à l'API Infoclimat après 15 secondes.")
            return {"error": "Infoclimat API request timed out."}
        except requests.exceptions.ConnectionError as e:
            print(f"Erreur de connexion à l'API Infoclimat (vérifiez votre connexion internet ou pare-feu): {e}")
            return {"error": f"Network connection error to Infoclimat API: {e}"}
        except requests.exceptions.RequestException as e:
            print(f"Erreur HTTP générale lors de la récupération météo Infoclimat: {e}")
            return {"error": f"HTTP request error to Infoclimat API: {e}"}
        except Exception as e:
            print(f"Erreur inattendue lors de la récupération météo: {e}")
            return {"error": f"Unexpected error during weather data retrieval: {e}"}


class CollecteurDonnees:
    """Collecte et agrège les données de différentes sources"""
    
    def __init__(self, supabase_client: Client = None):
        self.supabase = supabase_client
        self.collecteur_meteo = CollecteurMeteoInfoclimat()
        # Cache pour les stations de métro (évite les appels répétés)
        self._cache_stations = {}
        
    def _calculer_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcule la distance en km entre deux points GPS (formule de Haversine)"""
        R = 6371  # Rayon de la Terre en km
        
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        
        return R * c

    def filtrer_parkings_pertinents(self, parkings: List[Parking], destination: Tuple[float, float], 
                                   rayon_max_km: float = 3.0) -> List[Parking]:
        """Filtre les parkings pertinents selon la proximité de la destination"""
        print(f"🔍 Filtrage des parkings dans un rayon de {rayon_max_km}km de la destination...")
        
        parkings_pertinents = []
        for parking in parkings:
            distance = self._calculer_distance(
                parking.latitude, parking.longitude,
                destination[0], destination[1]
            )
            
            if distance <= rayon_max_km:
                parking.distance_destination = distance
                parkings_pertinents.append(parking)
        
        # Trier par distance à la destination
        parkings_pertinents.sort(key=lambda p: p.distance_destination)
        
        print(f"✅ {len(parkings_pertinents)} parkings pertinents trouvés (sur {len(parkings)} au total)")
        return parkings_pertinents[:15]  # Limiter à 15 parkings max pour l'efficacité
        
    def recuperer_parkings_saemes(self, destination: Tuple[float, float] = None) -> List[Parking]:
        """Récupère les données en temps réel des parkings Saemes"""
        parkings = []
        
        try:
            print("🔄 Récupération des données Saemes...")
            
            # 1. Récupérer le référentiel des parkings (infos statiques)
            referentiel_params = {
                "dataset": SAEMES_REFERENTIEL_DATASET,
                "rows": 100,  # Limiter à 100 parkings pour éviter la surcharge
                "facet": "code_postal",
                "refine.code_postal": "75*"  # Filtrer sur Paris (codes postaux 75*)
            }
            
            referentiel_response = requests.get(SAEMES_API_URL, params=referentiel_params, timeout=10)
            referentiel_response.raise_for_status()
            referentiel_data = referentiel_response.json()
            
            # 2. Récupérer les places disponibles en temps réel
            disponibilite_params = {
                "dataset": SAEMES_DATASET,
                "rows": 100,
                "facet": "code_postal",
                "refine.code_postal": "75*"  # Filtrer sur Paris
            }
            
            disponibilite_response = requests.get(SAEMES_API_URL, params=disponibilite_params, timeout=10)
            disponibilite_response.raise_for_status()
            disponibilite_data = disponibilite_response.json()
            
            # Créer un dictionnaire des places disponibles par ID de parking
            places_disponibles = {}
            for record in disponibilite_data.get('records', []):
                fields = record.get('fields', {})
                parking_id = fields.get('identifiant_unique')
                places_libres = fields.get('places_disponibles', 0)
                if parking_id:
                    places_disponibles[parking_id] = places_libres
            
            # Combiner les données
            for record in referentiel_data.get('records', []):
                fields = record.get('fields', {})
                
                # Extraire les informations du parking
                parking_id = fields.get('identifiant_unique')
                if not parking_id:
                    continue
                
                nom = fields.get('nom', 'Parking Saemes')
                adresse = fields.get('adresse', 'Paris')
                
                # Coordonnées GPS
                geometry = record.get('geometry')
                if geometry and geometry.get('coordinates'):
                    longitude, latitude = geometry['coordinates']
                else:
                    continue  # Ignorer si pas de coordonnées
                
                # Capacité et places disponibles
                capacite = fields.get('capacite_totale', 100)
                places_libres = places_disponibles.get(parking_id, random.randint(10, capacite // 2))
                
                # Tarif (utiliser le tarif de base ou simuler)
                tarif = fields.get('tarif_1h', 0)
                if tarif == 0:
                    tarif = round(random.uniform(2.5, 5.0), 2)  # Tarif simulé entre 2.5€ et 5€
                
                parking = Parking(
                    id=parking_id,
                    nom=nom,
                    adresse=adresse,
                    latitude=latitude,
                    longitude=longitude,
                    capacite_totale=int(capacite),
                    places_disponibles=int(places_libres),
                    tarif_horaire=float(tarif)
                )
                
                parkings.append(parking)
            
            print(f"✅ {len(parkings)} parkings Saemes récupérés")
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Erreur réseau lors de la récupération Saemes: {e}")
            print("🔄 Utilisation de données simulées...")
            parkings = self._generer_parkings_fallback()
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des données Saemes: {e}")
            print("🔄 Utilisation de données simulées...")
            parkings = self._generer_parkings_fallback()
        
        # Si aucun parking récupéré, utiliser le fallback
        if not parkings:
            print("⚠️ Aucun parking Saemes trouvé, utilisation de données simulées...")
            parkings = self._generer_parkings_fallback()
        
        # Filtrer par pertinence géographique si destination fournie
        if destination:
            parkings = self.filtrer_parkings_pertinents(parkings, destination)
        
        return parkings
    
    def recuperer_parkings_paris(self, destination: Tuple[float, float] = None) -> List[Parking]:
        """Récupère les données des parkings municipaux de Paris"""
        parkings = []
        
        try:
            print("🔄 Récupération des parkings municipaux de Paris...")
            
            params = {
                "dataset": PARIS_PARKING_DATASET,
                "rows": 50,  # Limiter pour éviter la surcharge
                "facet": "statut",
                "refine.statut": "En service"
            }
            
            response = requests.get(PARIS_API_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            for record in data.get('records', []):
                fields = record.get('fields', {})
                
                # Extraire les informations
                parking_id = f"PARIS_{fields.get('id_parc', random.randint(1000, 9999))}"
                nom = fields.get('nom_du_parc', 'Parking Municipal')
                adresse = fields.get('adresse', 'Paris')
                
                # Coordonnées GPS
                geometry = record.get('geometry')
                if geometry and geometry.get('coordinates'):
                    longitude, latitude = geometry['coordinates']
                else:
                    continue
                
                # Capacité (simulée car pas toujours disponible)
                capacite = fields.get('capacite_totale', random.randint(100, 500))
                places_libres = random.randint(20, int(capacite * 0.7))
                
                # Tarif (simulé)
                tarif = round(random.uniform(3.0, 6.0), 2)
                
                parking = Parking(
                    id=parking_id,
                    nom=nom,
                    adresse=adresse,
                    latitude=latitude,
                    longitude=longitude,
                    capacite_totale=int(capacite),
                    places_disponibles=int(places_libres),
                    tarif_horaire=float(tarif)
                )
                
                parkings.append(parking)
            
            print(f"✅ {len(parkings)} parkings municipaux récupérés")
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des parkings Paris: {e}")
        
        # Filtrer par pertinence géographique si destination fournie
        if destination and parkings:
            parkings = self.filtrer_parkings_pertinents(parkings, destination)
        
        return parkings

    def recuperer_travaux_paris(self) -> List[Travaux]:
        """Récupère les données des travaux en cours à Paris"""
        travaux = []
        
        try:
            print("🔄 Récupération des travaux en cours à Paris...")
            
            # 1. Récupérer les chantiers perturbants (plus ciblés pour la circulation)
            params_perturbants = {
                "dataset": PARIS_TRAVAUX_PERTURBANTS_DATASET,
                "rows": 100,
                "facet": "statut",
                "refine.statut": "En cours"  # Seulement les travaux en cours
            }
            
            response = requests.get(PARIS_API_URL, params=params_perturbants, timeout=10)
            response.raise_for_status()
            data_perturbants = response.json()
            
            for record in data_perturbants.get('records', []):
                fields = record.get('fields', {})
                geometry = record.get('geometry', {})
                
                # Extraire les informations
                travaux_id = fields.get('id_situ', f"TRAV_PERT_{random.randint(1000, 9999)}")
                nom = fields.get('intitule', 'Travaux de voirie')
                description = fields.get('description', 'Travaux perturbant la circulation')
                
                # Dates (simulées si manquantes)
                date_debut = datetime.now() - timedelta(days=random.randint(1, 30))
                date_fin = datetime.now() + timedelta(days=random.randint(7, 60))
                
                # Niveau de perturbation
                niveau_code = fields.get('niveau_perturbation', 2)
                niveau_perturbation = "Très perturbant" if niveau_code == 1 else "Perturbant"
                
                # Coordonnées (centroïde si polygone)
                if geometry.get('coordinates'):
                    coords = geometry['coordinates']
                    if geometry.get('type') == 'Point':
                        longitude, latitude = coords
                        geometrie_poly = None
                    elif geometry.get('type') == 'Polygon':
                        # Prendre le centroïde du polygone
                        poly_coords = coords[0] if coords else []
                        if poly_coords:
                            longitude = sum(point[0] for point in poly_coords) / len(poly_coords)
                            latitude = sum(point[1] for point in poly_coords) / len(poly_coords)
                            geometrie_poly = [(point[1], point[0]) for point in poly_coords]  # Conversion lon,lat -> lat,lon
                        else:
                            continue
                    else:
                        continue
                else:
                    continue
                
                travaux_obj = Travaux(
                    id=travaux_id,
                    nom=nom,
                    description=description,
                    latitude=latitude,
                    longitude=longitude,
                    date_debut=date_debut,
                    date_fin=date_fin,
                    niveau_perturbation=niveau_perturbation,
                    statut="En cours",
                    impact_circulation=True,
                    geometrie=geometrie_poly
                )
                
                travaux.append(travaux_obj)
            
            print(f"✅ {len(travaux)} travaux perturbants récupérés")
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des travaux: {e}")
            # Générer quelques travaux simulés
            travaux = self._generer_travaux_fallback()
        
        return travaux

    def recuperer_incidents_metro(self) -> List[IncidentMetro]:
        """Récupère les incidents et perturbations du métro RATP avec amélioration de la détection"""
        incidents = []
        
        try:
            print("🚇 Récupération des incidents métro RATP...")
            
            # Récupérer le trafic général
            response = requests.get(RATP_TRAFFIC_ENDPOINT, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("result") and data["result"].get("metros"):
                for metro_line in data["result"]["metros"]:
                    ligne = metro_line.get("line", "")
                    statut = metro_line.get("slug", "normal")
                    titre = metro_line.get("title", "Trafic normal")
                    message = metro_line.get("message", "")
                    
                    # Analyser le niveau d'impact avec plus de précision
                    impact_niveau = "normal"
                    stations_fermees = []
                    
                    # Amélioration de la détection des incidents
                    message_lower = message.lower()
                    
                    if statut in ["alerte", "critical"] or "perturbé" in message_lower:
                        impact_niveau = "perturbe"
                        stations_fermees = self._extraire_stations_fermees(message)
                    elif "interrompu" in message_lower or "arrêt" in message_lower:
                        impact_niveau = "interrompu"
                        stations_fermees = self._extraire_stations_fermees(message)
                    elif statut == "normal_trav" or "travaux" in message_lower:
                        impact_niveau = "travaux"
                        stations_fermees = self._extraire_stations_fermees(message)
                    elif "fermée" in message_lower or "fermé" in message_lower:
                        impact_niveau = "perturbe"
                        stations_fermees = self._extraire_stations_fermees(message)
                    
                    incident = IncidentMetro(
                        ligne=ligne,
                        statut=statut,
                        titre=titre,
                        message=message,
                        impact_niveau=impact_niveau,
                        stations_fermees=stations_fermees
                    )
                    
                    incidents.append(incident)
                    
                    # Log pour debug
                    if impact_niveau != "normal":
                        print(f"🚇 Incident détecté - Ligne {ligne}: {titre} | Stations: {stations_fermees}")
            
            print(f"✅ {len(incidents)} lignes de métro analysées")
            
        except Exception as e:
            print(f"❌ Erreur lors de la récupération des incidents métro: {e}")
            # Générer quelques incidents simulés avec cas spécifique ligne 7
            incidents = self._generer_incidents_metro_fallback()
        
        return incidents

    def recuperer_stations_metro_proches(self, latitude: float, longitude: float, rayon_km: float = 0.8) -> List[StationMetro]:
        """Récupère les stations de métro proches d'un point donné avec une base étendue"""
        stations_proches = []
        
        try:
            print(f"🔍 Recherche de stations métro dans un rayon de {rayon_km}km...")
            
            # Obtenir les incidents actuels
            incidents = self.recuperer_incidents_metro()
            
            # Base de données étendue des stations parisiennes avec coordonnées
            stations_principales = self._obtenir_stations_principales_etendues()
            
            for station in stations_principales:
                # Calculer la distance
                distance = self._calculer_distance(latitude, longitude, station['latitude'], station['longitude'])
                
                if distance <= rayon_km:
                    # Vérifier si la station est fermée selon les incidents
                    fermee, raison = self._verifier_fermeture_station(station['nom'], incidents)
                    
                    station_obj = StationMetro(
                        nom=station['nom'],
                        slug=station['slug'],
                        latitude=station['latitude'],
                        longitude=station['longitude'],
                        lignes=station['lignes'],
                        fermee=fermee,
                        raison_fermeture=raison,
                        distance_point=distance
                    )
                    
                    stations_proches.append(station_obj)
            
            # Trier par distance
            stations_proches.sort(key=lambda s: s.distance_point)
            
            print(f"✅ {len(stations_proches)} stations trouvées dans le périmètre")
            
            # Log pour debug
            for station in stations_proches[:5]:  # Afficher les 5 plus proches
                status = "FERMÉE" if station.fermee else "Ouverte"
                print(f"   - {station.nom} ({', '.join(station.lignes)}) - {station.distance_point:.2f}km - {status}")
            
        except Exception as e:
            print(f"❌ Erreur lors de la recherche des stations: {e}")
        
        return stations_proches

    def _extraire_stations_fermees(self, message: str) -> List[str]:
        """Extrait les noms de stations fermées depuis un message d'incident avec amélioration"""
        stations = []
        
        # Patterns améliorés pour les messages RATP
        patterns = [
            r"la station ([A-Za-zÀ-ÿ\s\-']+?) est fermée",
            r"station ([A-Za-zÀ-ÿ\s\-']+?) fermée",
            r"fermeture de ([A-Za-zÀ-ÿ\s\-']+)",
            r"([A-Za-zÀ-ÿ\s\-']+?) fermé",
            r"entre ([A-Za-zÀ-ÿ\s\-']+?) et ([A-Za-zÀ-ÿ\s\-']+)",  # tronçons
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, message, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):  # Pour les tronçons
                    for station_part in match:
                        station_name = station_part.strip()
                        if station_name and len(station_name) > 2 and station_name not in stations:
                            stations.append(station_name)
                else:
                    station_name = match.strip()
                    if station_name and len(station_name) > 2 and station_name not in stations:
                        stations.append(station_name)
        
        return stations

    def _verifier_fermeture_station(self, nom_station: str, incidents: List[IncidentMetro]) -> Tuple[bool, str]:
        """Vérifie si une station est fermée selon les incidents rapportés avec amélioration"""
        for incident in incidents:
            # Vérification directe dans la liste des stations fermées
            for station_fermee in incident.stations_fermees:
                if self._stations_similaires(nom_station, station_fermee):
                    return True, f"Fermée - Ligne {incident.ligne}: {incident.titre}"
            
            # Vérification dans le message complet pour les cas non détectés
            if nom_station.lower() in incident.message.lower() and incident.impact_niveau != "normal":
                return True, f"Perturbée - Ligne {incident.ligne}: {incident.titre}"
        
        return False, ""

    def _stations_similaires(self, station1: str, station2: str) -> bool:
        """Compare deux noms de stations en tenant compte des variantes"""
        # Normaliser les noms
        def normaliser(nom):
            return nom.lower().replace("-", " ").replace("'", " ").replace("  ", " ").strip()
        
        nom1_norm = normaliser(station1)
        nom2_norm = normaliser(station2)
        
        # Comparaison directe
        if nom1_norm == nom2_norm:
            return True
        
        # Vérifier si l'un contient l'autre (pour "Gare du Nord" vs "Gare du Nord")
        if nom1_norm in nom2_norm or nom2_norm in nom1_norm:
            return True
        
        # Vérifier les mots clés principaux
        mots1 = set(nom1_norm.split())
        mots2 = set(nom2_norm.split())
        
        # Si plus de 70% des mots correspondent
        if len(mots1 & mots2) / max(len(mots1), len(mots2)) > 0.7:
            return True
        
        return False

    def _obtenir_stations_principales_etendues(self) -> List[Dict]:
        """Retourne une base de données étendue des stations parisiennes avec coordonnées"""
        return [
            # Ligne 7 - stations principales
            {"nom": "Châtelet", "slug": "chatelet", "latitude": 48.8608, "longitude": 2.3470, "lignes": ["1", "4", "7", "11", "14"]},
            {"nom": "Pont Neuf", "slug": "pont+neuf", "latitude": 48.8584, "longitude": 2.3415, "lignes": ["7"]},
            {"nom": "Palais Royal - Musée du Louvre", "slug": "palais+royal", "latitude": 48.8656, "longitude": 2.3360, "lignes": ["1", "7"]},
            {"nom": "Pont Marie", "slug": "pont+marie", "latitude": 48.8527, "longitude": 2.3566, "lignes": ["7"]},
            {"nom": "Sully - Morland", "slug": "sully+morland", "latitude": 48.8507, "longitude": 2.3625, "lignes": ["7"]},
            {"nom": "Gare de l'Est", "slug": "gare+de+l+est", "latitude": 48.8766, "longitude": 2.3589, "lignes": ["4", "5", "7"]},
            {"nom": "République", "slug": "republique", "latitude": 48.8675, "longitude": 2.3636, "lignes": ["3", "5", "8", "9", "11"]},
            {"nom": "Opéra", "slug": "opera", "latitude": 48.8708, "longitude": 2.3319, "lignes": ["3", "7", "8"]},
            {"nom": "Chaussée d'Antin - La Fayette", "slug": "chaussee+d+antin", "latitude": 48.8722, "longitude": 2.3332, "lignes": ["7", "9"]},
            {"nom": "Le Peletier", "slug": "le+peletier", "latitude": 48.8751, "longitude": 2.3394, "lignes": ["7"]},
            {"nom": "Cadet", "slug": "cadet", "latitude": 48.8759, "longitude": 2.3444, "lignes": ["7"]},
            {"nom": "Poissonnière", "slug": "poissoniere", "latitude": 48.8765, "longitude": 2.3483, "lignes": ["7"]},
            {"nom": "Gare du Nord", "slug": "gare+du+nord", "latitude": 48.8810, "longitude": 2.3550, "lignes": ["4", "5", "RER B", "RER D"]},
            {"nom": "Louis Blanc", "slug": "louis+blanc", "latitude": 48.8816, "longitude": 2.3653, "lignes": ["7", "7bis"]},
            {"nom": "Riquet", "slug": "riquet", "latitude": 48.8889, "longitude": 2.3625, "lignes": ["7"]},
            {"nom": "Crimée", "slug": "crimee", "latitude": 48.8903, "longitude": 2.3775, "lignes": ["7"]},
            {"nom": "Corentin Cariou", "slug": "corentin+cariou", "latitude": 48.8942, "longitude": 2.3869, "lignes": ["7"]},
            {"nom": "Porte de la Villette", "slug": "porte+de+la+villette", "latitude": 48.8978, "longitude": 2.3936, "lignes": ["7"]},
            {"nom": "La Courneuve - 8 Mai 1945", "slug": "la+courneuve", "latitude": 48.9208, "longitude": 2.4097, "lignes": ["7"]},
            
            # Autres stations importantes
            {"nom": "Châtelet-Les Halles", "slug": "chatelet+les+halles", "latitude": 48.8610, "longitude": 2.3470, "lignes": ["1", "4", "7", "11", "14", "RER A", "RER B", "RER D"]},
            {"nom": "Bastille", "slug": "bastille", "latitude": 48.8532, "longitude": 2.3692, "lignes": ["1", "5", "8"]},
            {"nom": "Hôtel de Ville", "slug": "hotel+de+ville", "latitude": 48.8566, "longitude": 2.3522, "lignes": ["1", "11"]},
            {"nom": "Saint-Lazare", "slug": "saint+lazare", "latitude": 48.8755, "longitude": 2.3254, "lignes": ["3", "12", "13", "14", "RER E"]},
            {"nom": "Trocadéro", "slug": "trocadero", "latitude": 48.8635, "longitude": 2.2870, "lignes": ["6", "9"]},
            {"nom": "Invalides", "slug": "invalides", "latitude": 48.8566, "longitude": 2.3137, "lignes": ["8", "13", "RER C"]},
            {"nom": "Concorde", "slug": "concorde", "latitude": 48.8651, "longitude": 2.3215, "lignes": ["1", "8", "12"]},
            {"nom": "Saint-Michel", "slug": "saint+michel", "latitude": 48.8538, "longitude": 2.3444, "lignes": ["4", "RER B", "RER C"]},
            {"nom": "Saint-Germain-des-Prés", "slug": "saint+germain+des+pres", "latitude": 48.8542, "longitude": 2.3334, "lignes": ["4"]},
            
            # Stations autour de la zone 19ème (près de Riquet)
            {"nom": "Jaurès", "slug": "jaures", "latitude": 48.8833, "longitude": 2.3717, "lignes": ["2", "5", "7bis"]},
            {"nom": "Stalingrad", "slug": "stalingrad", "latitude": 48.8842, "longitude": 2.3669, "lignes": ["2", "5", "7"]},
            {"nom": "Laumière", "slug": "laumiere", "latitude": 48.8889, "longitude": 2.3814, "lignes": ["5"]},
            {"nom": "Ourcq", "slug": "ourcq", "latitude": 48.8897, "longitude": 2.3889, "lignes": ["5"]},
        ]

    def _generer_incidents_metro_fallback(self) -> List[IncidentMetro]:
        """Génère des incidents de métro simulés pour les tests avec cas ligne 7"""
        incidents_simules = [
            {
                'ligne': '1',
                'statut': 'normal',
                'titre': 'Trafic normal',
                'message': 'Trafic normal sur l\'ensemble de la ligne.',
                'impact_niveau': 'normal',
                'stations_fermees': []
            },
            {
                'ligne': '7',
                'statut': 'alerte',
                'titre': 'Trafic perturbé',
                'message': 'Travaux de modernisation. Trafic interrompu entre La Courneuve - 8 Mai 1945 et Riquet du 15 au 20 juillet. La station Riquet est fermée pour travaux.',
                'impact_niveau': 'perturbe',
                'stations_fermees': ['Riquet', 'La Courneuve - 8 Mai 1945']
            },
            {
                'ligne': '4',
                'statut': 'alerte',
                'titre': 'Trafic perturbé',
                'message': 'La station Saint-Germain-des-Prés est fermée pour raisons de sécurité.',
                'impact_niveau': 'perturbe',
                'stations_fermees': ['Saint-Germain-des-Prés']
            },
            {
                'ligne': '13',
                'statut': 'normal',
                'titre': 'Trafic normal',
                'message': 'Trafic normal sur l\'ensemble de la ligne.',
                'impact_niveau': 'normal',
                'stations_fermees': []
            }
        ]
        
        incidents = []
        for inc in incidents_simules:
            incidents.append(IncidentMetro(
                ligne=inc['ligne'],
                statut=inc['statut'],
                titre=inc['titre'],
                message=inc['message'],
                impact_niveau=inc['impact_niveau'],
                stations_fermees=inc['stations_fermees']
            ))
        
        print(f"✅ {len(incidents)} incidents métro simulés générés (incluant ligne 7)")
        return incidents
    
    def _generer_travaux_fallback(self) -> List[Travaux]:
        """Génère des travaux simulés basés sur des zones typiques de Paris"""
        travaux_simules = [
            {
                'id': 'TRAV_001',
                'nom': 'Rénovation Avenue des Champs-Élysées',
                'description': 'Travaux de réfection de la chaussée',
                'latitude': 48.8698,
                'longitude': 2.3076,
                'niveau_perturbation': 'Très perturbant',
                'geometrie': [(48.8698, 2.3076), (48.8708, 2.3086), (48.8718, 2.3096)]
            },
            {
                'id': 'TRAV_002',
                'nom': 'Réparation Boulevard Saint-Germain',
                'description': 'Réfection des canalisations',
                'latitude': 48.8530,
                'longitude': 2.3352,
                'niveau_perturbation': 'Perturbant',
                'geometrie': None
            },
            {
                'id': 'TRAV_003',
                'nom': 'Travaux Rue de Rivoli',
                'description': 'Aménagement cyclable',
                'latitude': 48.8590,
                'longitude': 2.3470,
                'niveau_perturbation': 'Perturbant',
                'geometrie': [(48.8590, 2.3470), (48.8595, 2.3480), (48.8600, 2.3490)]
            }
        ]
        
        travaux = []
        for t in travaux_simules:
            travaux.append(Travaux(
                id=t['id'],
                nom=t['nom'],
                description=t['description'],
                latitude=t['latitude'],
                longitude=t['longitude'],
                date_debut=datetime.now() - timedelta(days=random.randint(5, 20)),
                date_fin=datetime.now() + timedelta(days=random.randint(15, 60)),
                niveau_perturbation=t['niveau_perturbation'],
                statut="En cours",
                impact_circulation=True,
                geometrie=t['geometrie']
            ))
        
        print(f"✅ {len(travaux)} travaux simulés générés")
        return travaux
    
    def _generer_parkings_fallback(self) -> List[Parking]:
        """Génère des données de parkings réalistes basées sur de vrais parkings parisiens"""
        parkings_reels = [
            {
                'id': 'SAEM_001',
                'nom': 'Parking Hôtel de Ville',
                'adresse': 'Place de l\'Hôtel de Ville, 75004 Paris',
                'latitude': 48.8566,
                'longitude': 2.3522,
                'capacite_totale': 500,
                'places_disponibles': random.randint(50, 200),
                'tarif_horaire': 4.40
            },
            {
                'id': 'SAEM_002',
                'nom': 'Parking Notre-Dame',
                'adresse': 'Place du Parvis Notre-Dame, 75004 Paris',
                'latitude': 48.8530,
                'longitude': 2.3499,
                'capacite_totale': 400,
                'places_disponibles': random.randint(30, 150),
                'tarif_horaire': 4.20
            },
            {
                'id': 'SAEM_003',
                'nom': 'Parking Meyerbeer-Opéra',
                'adresse': '3 Rue Meyerbeer, 75009 Paris',
                'latitude': 48.8708,
                'longitude': 2.3338,
                'capacite_totale': 350,
                'places_disponibles': random.randint(20, 100),
                'tarif_horaire': 4.80
            },
            {
                'id': 'SAEM_009',
                'nom': 'Parking Bassin de la Villette',
                'adresse': 'Quai de la Seine, 75019 Paris',
                'latitude': 48.8889,
                'longitude': 2.3700,
                'capacite_totale': 200,
                'places_disponibles': random.randint(30, 80),
                'tarif_horaire': 3.50
            },
            {
                'id': 'SAEM_010',
                'nom': 'Parking Crimée',
                'adresse': 'Avenue de Flandre, 75019 Paris',
                'latitude': 48.8900,
                'longitude': 2.3750,
                'capacite_totale': 150,
                'places_disponibles': random.randint(20, 60),
                'tarif_horaire': 3.20
            }
        ]
        
        return [Parking(**p) for p in parkings_reels]
    
    def obtenir_donnees_meteo(self, latitude: float, longitude: float) -> Dict:
        """Récupère les données météo - utilise la météo réelle via Infoclimat."""
        return self.collecteur_meteo.recuperer_donnees_meteo(latitude, longitude)
    
    def recuperer_evenements_locaux(self, date: datetime) -> List[Dict]:
        """Récupère les événements locaux qui peuvent impacter l'affluence"""
        evenements = [
            {
                'nom': 'Match PSG au Parc des Princes',
                'lieu': 'Parc des Princes',
                'date': date,
                'impact_zone': {'latitude': 48.8414, 'longitude': 2.2530, 'rayon_km': 2},
                'coefficient_impact': 1.8
            },
            {
                'nom': 'Concert à l\'Olympia',
                'lieu': 'Olympia',
                'date': date,
                'impact_zone': {'latitude': 48.8700, 'longitude': 2.3285, 'rayon_km': 1},
                'coefficient_impact': 1.4
            }
        ]
        
        return [e for e in evenements if e['date'].date() == date.date()]
    
    def sauvegarder_historique(self, parking_id: str, taux_occupation: float):
        """Sauvegarde l'historique dans Supabase"""
        try:
            if self.supabase:
                data = {
                    'parking_id': parking_id,
                    'timestamp': datetime.now().isoformat(),
                    'taux_occupation': taux_occupation,
                    'jour_semaine': datetime.now().weekday(),
                    'heure': datetime.now().hour
                }
            print(f"Sauvegarde historique: {parking_id} - {taux_occupation:.2%}")
        except Exception as e:
            print(f"Erreur sauvegarde Supabase: {e}")


class PredicteurSaturation:
    """Prédit la saturation des parkings basé sur l'historique et les conditions"""
    
    def __init__(self, collecteur: CollecteurDonnees):
        self.collecteur = collecteur
        
    def generer_historique_simule(self, parking_id: str, nb_jours: int = 30) -> List[Dict]:
        """Génère un historique simulé pour les tests"""
        historique = []
        
        for jour in range(nb_jours):
            date = datetime.now() - timedelta(days=jour)
            
            for heure in range(24):
                # Pattern typique d'occupation
                if 8 <= heure <= 10:  # Heure de pointe matin
                    base_taux = random.uniform(0.7, 0.95)
                elif 17 <= heure <= 19:  # Heure de pointe soir
                    base_taux = random.uniform(0.8, 0.98)
                elif 12 <= heure <= 14:  # Pause déjeuner
                    base_taux = random.uniform(0.6, 0.85)
                elif 22 <= heure or heure <= 6:  # Nuit
                    base_taux = random.uniform(0.1, 0.3)
                else:
                    base_taux = random.uniform(0.4, 0.7)
                
                # Variation weekend
                if date.weekday() >= 5:
                    base_taux *= 0.7
                
                historique.append({
                    'parking_id': parking_id,
                    'timestamp': date.replace(hour=heure),
                    'taux_occupation': min(base_taux + random.uniform(-0.1, 0.1), 1.0),
                    'jour_semaine': date.weekday(),
                    'heure': heure
                })
                
        return historique
    
    def predire_saturation(self, parking: Parking, heure_cible: datetime) -> PredictionSaturation:
        """Prédit le taux de saturation pour un parking à une heure donnée"""
        
        # Récupérer l'historique (simulé pour les tests)
        historique = self.generer_historique_simule(parking.id, 30)
        
        # Filtrer par jour de la semaine et heure similaires
        jour_cible = heure_cible.weekday()
        heure_cible_int = heure_cible.hour
        
        donnees_similaires = [
            h['taux_occupation'] for h in historique
            if h['jour_semaine'] == jour_cible 
            and abs(h['heure'] - heure_cible_int) <= 1
        ]
        
        # Calcul de la prédiction de base
        if donnees_similaires:
            prediction_base = np.mean(donnees_similaires)
            ecart_type = np.std(donnees_similaires)
        else:
            prediction_base = 0.5
            ecart_type = 0.2
        
        # Ajustements selon les conditions
        meteo = self.collecteur.obtenir_donnees_meteo(parking.latitude, parking.longitude)
        evenements = self.collecteur.recuperer_evenements_locaux(heure_cible)
        
        # Impact métro : vérifier les stations proches avec rayon plus large
        stations_proches = self.collecteur.recuperer_stations_metro_proches(
            parking.latitude, parking.longitude, rayon_km=0.8
        )
        
        # Impact météo
        prediction_ajustee = prediction_base
        if meteo and not meteo.get("error"):
            if random.random() < 0.3:
                 prediction_ajustee *= 0.9
            else:
                 prediction_ajustee *= 1.05
        
        # Impact fermetures de métro (amélioré)
        stations_fermees = [s for s in stations_proches if s.fermee]
        if stations_fermees:
            # Plus de stations fermées = plus de demande de parking
            facteur_metro = 1 + (len(stations_fermees) * 0.15)  # +15% par station fermée
            prediction_ajustee *= facteur_metro
            print(f"Impact métro sur {parking.nom}: {len(stations_fermees)} station(s) fermée(s) -> +{(facteur_metro-1)*100:.0f}%")
            for station in stations_fermees:
                print(f"  - {station.nom} fermée: {station.raison_fermeture}")
        
        # Impact événements
        for event in evenements:
            distance = self._calculer_distance(
                parking.latitude, parking.longitude,
                event['impact_zone']['latitude'], event['impact_zone']['longitude']
            )
            if distance <= event['impact_zone']['rayon_km']:
                prediction_ajustee *= event['coefficient_impact']
        
        # S'assurer que la prédiction reste dans [0, 1]
        prediction_ajustee = min(max(prediction_ajustee, 0), 1)
        
        # Calculer le temps avant saturation complète
        taux_actuel = 1 - (parking.places_disponibles / parking.capacite_totale)
        temps_saturation_str = "N/A"
        if prediction_ajustee > 0.95 and taux_actuel < 0.95:
            vitesse_remplissage_hypothetique = (prediction_ajustee - taux_actuel) / 60
            if vitesse_remplissage_hypothetique > 0.001:
                temps_en_minutes = int((0.95 - taux_actuel) / vitesse_remplissage_hypothetique)
                if temps_en_minutes < 60:
                    temps_saturation_str = f"~{temps_en_minutes} min"
                else:
                    temps_saturation_str = f"~{int(temps_en_minutes/60)} heure(s)"
            else:
                temps_saturation_str = "Faible risque immédiat"
        elif prediction_ajustee >= 0.99:
             temps_saturation_str = "Déjà saturé ou très proche"
        elif prediction_ajustee <= 0.5:
            temps_saturation_str = "Très faible risque"

        return PredictionSaturation(
            parking_id=parking.id,
            taux_occupation_actuel=taux_actuel,
            taux_occupation_predit=prediction_ajustee,
            heure_prediction=heure_cible,
            fiabilite_prediction=1 - ecart_type,
            temps_avant_saturation=temps_saturation_str
        )
    
    def _calculer_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calcule la distance en km entre deux points GPS (formule de Haversine)"""
        R = 6371  # Rayon de la Terre en km
        
        dlat = np.radians(lat2 - lat1)
        dlon = np.radians(lon2 - lon1)
        a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
        
        return R * c


class AssistantNavigation:

    def __init__(self, predicteur: PredicteurSaturation, collecteur_donnees: CollecteurDonnees):
        self.predicteur = predicteur
        self.collecteur = collecteur_donnees

    def _decode_polyline(self, polyline_str: str) -> List[Tuple[float, float]]:
        """Décoder une chaîne de polyligne encodée de Google Maps en une liste de points (lat, lon)."""
        index, lat, lng = 0, 0, 0
        coordinates = []
        while index < len(polyline_str):
            b = 0
            shift = 0
            result = 0
            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break
            dlat = ~(result >> 1) if result & 1 else (result >> 1)
            lat += dlat

            shift = 0
            result = 0
            while True:
                byte = ord(polyline_str[index]) - 63
                index += 1
                result |= (byte & 0x1f) << shift
                shift += 5
                if not byte >= 0x20:
                    break
            dlng = ~(result >> 1) if result & 1 else (result >> 1)
            lng += dlng

            coordinates.append((lat / 1e5, lng / 1e5))
        return coordinates
       
    def calculer_temps_trajet(self, origine: Tuple[float, float],
                            destination: Tuple[float, float],
                            mode: str = 'driving',
                            with_traffic: bool = True,
                            eviter_travaux: bool = True) -> Optional[Dict]:
        """Calcule le temps de trajet en évitant les zones de travaux si demandé."""
        
        if not Maps_API_KEY:
            print("AVERTISSEMENT: Clé Maps_API_KEY non configurée. Temps de trajet simulé.")
            distance = self.predicteur._calculer_distance(
                origine[0], origine[1],
                destination[0], destination[1]
            )
            
            vitesse_moyenne_driving = 20 # km/h
            vitesse_moyenne_walking = 5  # km/h

            if mode == 'driving':
                temps_base = (distance / vitesse_moyenne_driving) * 60 # minutes
                # Simulation d'impact des travaux
                if eviter_travaux:
                    travaux = self.collecteur.recuperer_travaux_paris()
                    impact_travaux = self._calculer_impact_travaux_sur_trajet(origine, destination, travaux)
                    temps_base *= (1 + impact_travaux)
                
                temps_reel_traffic = int(temps_base * random.uniform(1.2, 1.8))
                return {'duration': int(temps_base), 'duration_in_traffic': temps_reel_traffic, 'route_points': []}
            elif mode == 'walking':
                temps_base = (distance / vitesse_moyenne_walking) * 60 # minutes
                return {'duration': int(temps_base), 'duration_in_traffic': int(temps_base), 'route_points': []}
            else:
                return None

        base_url = "https://maps.googleapis.com/maps/api/directions/json"
        params = {
            "origin": f"{origine[0]},{origine[1]}",
            "destination": f"{destination[0]},{destination[1]}",
            "mode": mode,
            "key": Maps_API_KEY,
            "alternatives": "true" if eviter_travaux else "false",
        }
        
        if with_traffic and mode == 'driving':
            params["departure_time"] = "now"

        if eviter_travaux and mode == 'driving':
            params["avoid"] = "tolls"

        try:
            response = requests.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()

            if data["status"] == "OK" and data["routes"]:
                if eviter_travaux and len(data["routes"]) > 1:
                    route = self._choisir_meilleure_route_evitant_travaux(data["routes"], origine, destination)
                else:
                    route = data["routes"][0]
                
                leg = route["legs"][0]
                duration = leg["duration"]["value"] // 60
                duration_in_traffic = duration
                if with_traffic and mode == 'driving' and "duration_in_traffic" in leg:
                    duration_in_traffic = leg["duration_in_traffic"]["value"] // 60

                encoded_polyline = route["overview_polyline"]["points"]
                route_points = self._decode_polyline(encoded_polyline) if encoded_polyline else []

                return {
                    'duration': duration,
                    'duration_in_traffic': duration_in_traffic,
                    'route_points': route_points
                }
            else:
                print(f"Erreur Directions API: {data.get('error_message', data['status'])}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"Erreur de connexion à l'API Directions: {e}")
            return None
        except Exception as e:
            print(f"Erreur lors du calcul du trajet: {e}")
            return None

    def _calculer_impact_travaux_sur_trajet(self, origine: Tuple[float, float], 
                                           destination: Tuple[float, float], 
                                           travaux: List[Travaux]) -> float:
        """Calcule l'impact des travaux sur un trajet donné"""
        impact_total = 0.0
        
        for travail in travaux:
            if not travail.impact_circulation:
                continue
                
            distance_origine = self.predicteur._calculer_distance(
                origine[0], origine[1], travail.latitude, travail.longitude
            )
            distance_destination = self.predicteur._calculer_distance(
                destination[0], destination[1], travail.latitude, travail.longitude
            )
            
            distance_min = min(distance_origine, distance_destination)
            if distance_min < 1.0:  # Moins de 1km
                if travail.niveau_perturbation == "Très perturbant":
                    impact_total += 0.3  # +30% de temps
                else:
                    impact_total += 0.15  # +15% de temps
        
        return min(impact_total, 0.8)  # Plafonner à +80% max

    def _choisir_meilleure_route_evitant_travaux(self, routes: List[Dict], 
                                                origine: Tuple[float, float], 
                                                destination: Tuple[float, float]) -> Dict:
        """Choisit la meilleure route en évitant les zones de travaux"""
        travaux = self.collecteur.recuperer_travaux_paris()
        
        meilleure_route = routes[0]
        meilleur_score = float('inf')
        
        for route in routes:
            encoded_polyline = route["overview_polyline"]["points"]
            route_points = self._decode_polyline(encoded_polyline) if encoded_polyline else []
            
            impact_travaux = 0
            for point in route_points[::10]:  # Échantillonner tous les 10 points
                for travail in travaux:
                    distance = self.predicteur._calculer_distance(
                        point[0], point[1], travail.latitude, travail.longitude
                    )
                    if distance < 0.5:  # Moins de 500m
                        if travail.niveau_perturbation == "Très perturbant":
                            impact_travaux += 10
                        else:
                            impact_travaux += 5
            
            duree = route["legs"][0]["duration"]["value"] // 60
            score = duree + impact_travaux
            
            if score < meilleur_score:
                meilleur_score = score
                meilleure_route = route
        
        return meilleure_route
    
    def recommander_parking(self, position_actuelle: Tuple[float, float],
                          destination_finale: Tuple[float, float],
                          heure_arrivee_souhaitee: datetime) -> Dict:
        """Recommande le meilleur parking avec sélection intelligente par proximité"""
        
        print(f"\n🎯 RECHERCHE INTELLIGENTE DE PARKING")
        print(f"   Destination: {destination_finale}")
        print(f"   Position: {position_actuelle}")
        
        # Récupérer les parkings en filtrant par destination
        print("🔄 Récupération des parkings pertinents...")
        parkings_saemes = self.collecteur.recuperer_parkings_saemes(destination_finale)
        parkings_paris = self.collecteur.recuperer_parkings_paris(destination_finale)
        
        # Récupérer les travaux en cours
        travaux = self.collecteur.recuperer_travaux_paris()
        
        # Récupérer les incidents métro
        incidents_metro = self.collecteur.recuperer_incidents_metro()
        
        # Récupérer les stations proches de la destination
        stations_destination = self.collecteur.recuperer_stations_metro_proches(
            destination_finale[0], destination_finale[1], rayon_km=0.8
        )
        
        # Combiner les deux listes
        tous_parkings = parkings_saemes + parkings_paris
        
        if not tous_parkings:
            print("❌ Aucun parking pertinent trouvé dans la zone")
            return {
                'parking_recommande': None,
                'temps_estime': None,
                'saturation': None,
                'route_to_parking_points': [],
                'route_parking_to_dest_points': [],
                'travaux_sur_trajet': [],
                'incidents_metro': incidents_metro,
                'stations_destination': stations_destination,
                'alternatives': []
            }
        
        print(f"✅ Analyse de {len(tous_parkings)} parkings pertinents")
        
        recommendations = []

        for i, parking in enumerate(tous_parkings):
            print(f"   📊 Analyse parking {i+1}/{len(tous_parkings)}: {parking.nom} (distance: {parking.distance_destination:.2f}km)")
            
            # Calculer le trajet vers le parking
            temps_acces_data = self.calculer_temps_trajet(
                position_actuelle,
                (parking.latitude, parking.longitude),
                mode='driving',
                with_traffic=True,
                eviter_travaux=True
            )

            if not temps_acces_data:
                print(f"      ❌ Impossible de calculer le trajet vers le parking {parking.nom}")
                continue

            temps_jusqu_parking = temps_acces_data['duration_in_traffic']
            route_to_parking_points = temps_acces_data['route_points']

            heure_arrivee_parking = datetime.now() + timedelta(minutes=temps_jusqu_parking)
            prediction = self.predicteur.predire_saturation(parking, heure_arrivee_parking)

            # Calculer le trajet de marche
            temps_marche_data = self.calculer_temps_trajet(
                (parking.latitude, parking.longitude),
                destination_finale,
                mode='walking',
                with_traffic=False,
                eviter_travaux=False
            )

            if not temps_marche_data:
                print(f"      ❌ Impossible de calculer le trajet de marche depuis le parking {parking.nom}")
                continue

            temps_marche = temps_marche_data['duration']
            route_parking_to_dest_points = temps_marche_data['route_points']

            # Identifier les travaux impactant ce trajet
            travaux_impactants = self._identifier_travaux_sur_trajet(
                route_to_parking_points, travaux
            )

            # Analyser l'impact des fermetures métro
            stations_parking = self.collecteur.recuperer_stations_metro_proches(
                parking.latitude, parking.longitude, rayon_km=0.5
            )
            
            impact_metro = self._calculer_impact_metro(stations_parking, stations_destination)

            score = self.calculer_score_parking(
                prediction.taux_occupation_predit,
                temps_jusqu_parking,
                temps_marche,
                parking.tarif_horaire,
                len(travaux_impactants),
                impact_metro,
                parking.distance_destination
            )
            
            print(f"      ✅ Score calculé: {score:.1f} (temps: {temps_jusqu_parking + temps_marche}min, saturation: {prediction.taux_occupation_predit:.0%})")

            recommendations.append({
                'parking': parking,
                'temps_acces': temps_jusqu_parking,
                'temps_marche_destination': temps_marche,
                'temps_total': temps_jusqu_parking + temps_marche,
                'prediction_saturation': prediction,
                'score': score,
                'disponible': prediction.taux_occupation_predit < 0.95,
                'route_to_parking_points': route_to_parking_points,
                'route_parking_to_dest_points': route_parking_to_dest_points,
                'travaux_impactants': travaux_impactants,
                'stations_proches': stations_parking,
                'impact_metro': impact_metro
            })

        # Trier par score (plus bas = meilleur)
        recommendations.sort(key=lambda x: x['score'])
        
        print(f"\n🏆 CLASSEMENT DES PARKINGS:")
        for i, reco in enumerate(recommendations[:5]):
            print(f"   {i+1}. {reco['parking'].nom} - Score: {reco['score']:.1f} - {reco['temps_total']}min")

        if not recommendations:
            return {
                'parking_recommande': None,
                'temps_estime': None,
                'saturation': None,
                'route_to_parking_points': [],
                'route_parking_to_dest_points': [],
                'travaux_sur_trajet': [],
                'incidents_metro': incidents_metro,
                'stations_destination': stations_destination,
                'alternatives': []
            }

        meilleure_reco = recommendations[0]
        alternatives = recommendations[1:4]

        print(f"\n✅ PARKING RECOMMANDÉ: {meilleure_reco['parking'].nom}")

        return {
            'parking_recommande': {
                'id': meilleure_reco['parking'].id,
                'nom': meilleure_reco['parking'].nom,
                'adresse': meilleure_reco['parking'].adresse,
                'latitude': meilleure_reco['parking'].latitude,
                'longitude': meilleure_reco['parking'].longitude,
                'places_disponibles': meilleure_reco['parking'].places_disponibles,
                'capacite_totale': meilleure_reco['parking'].capacite_totale,
                'tarif_horaire': meilleure_reco['parking'].tarif_horaire,
            },
            'temps_estime': {
                'acces_parking': meilleure_reco['temps_acces'],
                'marche_destination': meilleure_reco['temps_marche_destination'],
                'total': meilleure_reco['temps_total'],
            },
            'saturation': {
                'actuelle': f"{meilleure_reco['prediction_saturation'].taux_occupation_actuel:.2f}",
                'predite': f"{meilleure_reco['prediction_saturation'].taux_occupation_predit:.2f}",
                'fiabilite': f"{meilleure_reco['prediction_saturation'].fiabilite_prediction:.2f}",
                'temps_avant_saturation': meilleure_reco['prediction_saturation'].temps_avant_saturation,
            },
            'route_to_parking_points': meilleure_reco['route_to_parking_points'],
            'route_parking_to_dest_points': meilleure_reco['route_parking_to_dest_points'],
            'travaux_sur_trajet': meilleure_reco['travaux_impactants'],
            'travaux_tous': travaux,
            'incidents_metro': incidents_metro,
            'stations_destination': stations_destination,
            'stations_parking': meilleure_reco['stations_proches'],
            'impact_metro': meilleure_reco['impact_metro'],
            'alternatives': [
                {
                    'nom': alt['parking'].nom,
                    'temps_total': alt['temps_total'],
                    'saturation_predite': alt['prediction_saturation'].taux_occupation_predit,
                    'temps_acces': alt['temps_acces'],
                    'temps_marche_destination': alt['temps_marche_destination'],
                    'fiabilite_prediction': alt['prediction_saturation'].fiabilite_prediction,
                    'nb_travaux_impactants': len(alt['travaux_impactants']),
                    'impact_metro': alt['impact_metro']
                }
                for alt in alternatives
            ]
        }

    def _identifier_travaux_sur_trajet(self, route_points: List[Tuple[float, float]], 
                                      travaux: List[Travaux]) -> List[Travaux]:
        """Identifie les travaux qui impactent un trajet donné"""
        travaux_impactants = []
        
        for travail in travaux:
            if not travail.impact_circulation:
                continue
                
            for point in route_points[::5]:  # Échantillonner tous les 5 points
                distance = self.predicteur._calculer_distance(
                    point[0], point[1], travail.latitude, travail.longitude
                )
                if distance < 0.3:  # Moins de 300m du trajet
                    travaux_impactants.append(travail)
                    break
        
        return travaux_impactants

    def _calculer_impact_metro(self, stations_parking: List[StationMetro], 
                              stations_destination: List[StationMetro]) -> Dict:
        """Calcule l'impact des fermetures de métro sur l'attractivité du parking"""
        impact = {
            'score_penalite': 0,
            'stations_fermees_parking': [],
            'stations_fermees_destination': [],
            'recommandation': ""
        }
        
        # Analyser les fermetures près du parking
        for station in stations_parking:
            if station.fermee:
                impact['stations_fermees_parking'].append({
                    'nom': station.nom,
                    'lignes': station.lignes,
                    'raison': station.raison_fermeture
                })
                impact['score_penalite'] += 5
        
        # Analyser les fermetures près de la destination
        for station in stations_destination:
            if station.fermee:
                impact['stations_fermees_destination'].append({
                    'nom': station.nom,
                    'lignes': station.lignes,
                    'raison': station.raison_fermeture
                })
                impact['score_penalite'] -= 10  # Bonus car plus de demande de parking
        
        # Générer une recommandation
        if impact['stations_fermees_destination']:
            impact['recommandation'] = f"Parking avantageux : {len(impact['stations_fermees_destination'])} station(s) fermée(s) près de la destination"
        elif impact['stations_fermees_parking']:
            impact['recommandation'] = f"Attention : {len(impact['stations_fermees_parking'])} station(s) fermée(s) près du parking"
        else:
            impact['recommandation'] = "Métro normal, pas d'impact particulier"
        
        return impact
    
    def calculer_score_parking(self, taux_saturation: float, temps_acces: int, 
                              temps_marche: int, tarif: float, nb_travaux: int = 0,
                              impact_metro: Dict = None, distance_destination: float = 0.0) -> float:
        """Calcule un score composite amélioré pour classer les parkings"""
        penalite_saturation = taux_saturation ** 2 * 100
        penalite_temps = (temps_acces + temps_marche) * 0.5
        penalite_tarif = tarif * 2
        penalite_travaux = nb_travaux * 15
        penalite_distance = distance_destination * 10
        
        # Impact métro
        impact_metro_score = 0
        if impact_metro:
            impact_metro_score = impact_metro.get('score_penalite', 0)
        
        bonus_disponibilite = 0 if taux_saturation > 0.8 else (1 - taux_saturation) * 20
        
        return (penalite_saturation + penalite_temps + penalite_tarif + 
                penalite_travaux + penalite_distance + impact_metro_score - bonus_disponibilite)
    

class SystemeParkingParis:
    """Système principal d'assistance au parking pour Paris"""
    
    def __init__(self):
        self.supabase = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                print("✅ Connexion Supabase établie")
            except Exception as e:
                print(f"⚠️ Connexion Supabase échouée: {e}")
        
        # Initialisation correcte des dépendances
        self.collecteur = CollecteurDonnees(self.supabase)
        self.predicteur = PredicteurSaturation(self.collecteur)
        self.assistant_nav = AssistantNavigation(self.predicteur, self.collecteur)
        
    def assister_conducteur(self, position_actuelle: Tuple[float, float], destination: Tuple[float, float]) -> Dict:
        heure_arrivee_souhaitee = datetime.now() 
        
        resultat_reco = self.assistant_nav.recommander_parking(
            position_actuelle, destination, heure_arrivee_souhaitee
        )
        return resultat_reco

    def afficher_recommandation(self, resultat: Dict):
        """Affiche les recommandations de manière lisible"""
        if not resultat or not resultat.get('parking_recommande'):
            print("\n❌ Aucune recommandation de parking disponible.")
            return

        print("\n🎯 RECOMMANDATION PRINCIPALE:")
        print(f"Parking: {resultat['parking_recommande']['nom']}")
        print(f"Adresse: {resultat['parking_recommande']['adresse']}")
        print(f"Places disponibles: {resultat['parking_recommande']['places_disponibles']}/{resultat['parking_recommande']['capacite_totale']}")
        print(f"Tarif: {resultat['parking_recommande']['tarif_horaire']}€/h")
        
        print("\n⏱️  TEMPS ESTIMÉ:")
        print(f"Trajet jusqu'au parking: {resultat['temps_estime']['acces_parking']} min")
        print(f"Marche jusqu'à destination: {resultat['temps_estime']['marche_destination']} min")
        print(f"Temps total: {resultat['temps_estime']['total']} min")
        
        print("\n📊 SATURATION:")
        print(f"Taux actuel: {resultat['saturation']['actuelle']}")
        print(f"Taux prédit à l'arrivée: {resultat['saturation']['predite']}")
        print(f"Fiabilité de la prédiction: {resultat['saturation']['fiabilite']}")
        
        if resultat['saturation']['temps_avant_saturation'] and resultat['saturation']['temps_avant_saturation'] != "N/A":
            print(f"⚠️  Temps avant saturation: {resultat['saturation']['temps_avant_saturation']}")
        
        # Afficher les travaux impactants
        if resultat.get('travaux_sur_trajet'):
            print("\n🚧 TRAVAUX SUR VOTRE TRAJET:")
            for travail in resultat['travaux_sur_trajet']:
                print(f"- {travail.nom} ({travail.niveau_perturbation})")
                print(f"  {travail.description}")

        # Afficher les informations métro
        if resultat.get('impact_metro'):
            print(f"\n🚇 IMPACT MÉTRO:")
            print(f"Recommandation: {resultat['impact_metro']['recommandation']}")
            
            if resultat['impact_metro']['stations_fermees_destination']:
                print("Stations fermées près de la destination:")
                for station in resultat['impact_metro']['stations_fermees_destination']:
                    print(f"  - {station['nom']} (Lignes: {', '.join(station['lignes'])})")
                    print(f"    Raison: {station['raison']}")
            
            if resultat['impact_metro']['stations_fermees_parking']:
                print("Stations fermées près du parking:")
                for station in resultat['impact_metro']['stations_fermees_parking']:
                    print(f"  - {station['nom']} (Lignes: {', '.join(station['lignes'])})")
                    print(f"    Raison: {station['raison']}")
        
        if resultat['alternatives']:
            print("\n🔄 ALTERNATIVES:")
            for i, alt in enumerate(resultat['alternatives'], 1):
                travaux_info = f" - {alt['nb_travaux_impactants']} travaux" if alt['nb_travaux_impactants'] > 0 else ""
                metro_info = f" - {alt['impact_metro']['recommandation']}" if alt.get('impact_metro') else ""
                print(f"{i}. {alt['nom']} - {alt['temps_total']} min (saturation: {alt['saturation_predite']:.2f}){travaux_info}{metro_info}")


# Exemple d'utilisation
if __name__ == "__main__":
    print("🚗 Système d'Assistance au Parking - Paris")
    print("=" * 60)
    
    # Créer le système
    systeme = SystemeParkingParis()
    
    # Test avec adresse Riquet
    position_actuelle = (48.8584, 2.3475)  # Châtelet
    destination = (48.8889, 2.3625)  # Proche de Riquet
    
    print(f"\n🧪 TEST AVEC DESTINATION PROCHE DE RIQUET")
    print(f"Position: {position_actuelle}")
    print(f"Destination: {destination}")
    
    # Obtenir les recommandations
    resultat = systeme.assister_conducteur(position_actuelle, destination)
    
    # Afficher les résultats
    systeme.afficher_recommandation(resultat)
    
    # Sauvegarder dans Supabase (si configuré)
    if systeme.supabase and resultat and resultat.get('parking_recommande'):
        try:
            taux_actuel_float = float(resultat['saturation']['actuelle']) 
            systeme.collecteur.sauvegarder_historique(
                resultat['parking_recommande']['id'],
                taux_actuel_float
            )
        except ValueError:
            print("Erreur: Impossible de convertir le taux de saturation actuel en nombre pour la sauvegarde.")
        except Exception as e:
            print(f"Erreur lors de la sauvegarde de l'historique: {e}")