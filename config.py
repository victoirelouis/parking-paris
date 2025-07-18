import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
INFOCLIMAT_API_KEY = os.getenv('INFOCLIMAT_API_KEY')

# API endpoints
SAEMES_API_URL = "https://opendata.paris.fr/api/records/1.0/search/"
SAEMES_DATASET = "places-disponibles-parkings-saemes"
INFOCLIMAT_API_URL = "http://www.infoclimat.fr/public-api/gfs/json"

# Coordonnées Paris
PARIS_COORDS = {
    'hotel_ville': (48.8566, 2.3522),
    'notre_dame': (48.8530, 2.3499),
    'opera': (48.8708, 2.3338)
}