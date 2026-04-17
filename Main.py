import os, sys, re, logging, time, warnings, cv2
import torch, timm, pythoncom, easyocr
import numpy as np
from PIL import Image
from timm.data import resolve_data_config, create_transform
from win32com.propsys import propsys
from win32com.shell import shellcon

CHART_MODEL = timm.create_model("hf_hub:StephanAkkerman/chart-recognizer", pretrained=True)
CHART_MODEL.eval()
CHART_CONFIG = resolve_data_config(CHART_MODEL.pretrained_cfg, model=CHART_MODEL)
CHART_TRANSFORM = create_transform(**CHART_CONFIG)
CHART_LABELS = CHART_MODEL.pretrained_cfg["label_names"]

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
os.environ['TF_ENABLE_ONEDNN_OPTS'] = '0'
warnings.filterwarnings('ignore')

print("-" * 30)
if torch.cuda.is_available():
    print(f"🚀 GPU Active: {torch.cuda.get_device_name(0)}")
    DEVICE = "cuda"
else:
    DEVICE = "cpu"
    print("⚠️ GPU NOT DETECTED - Running on slow CPU mode")
print("-" * 30)

# Initialize EasyOCR
EASYOCR_READER = easyocr.Reader(['en'], gpu=True if DEVICE == "cuda" else False)


##Logging/Images
base_dir = os.path.dirname(os.path.abspath(__file__))
images_dir = os.path.join(base_dir, 'images')
os.makedirs(images_dir, exist_ok=True)

# 1. Setup Site Packages (if you must manually inject them)
venv_site_pkgs = os.path.join(base_dir, '.venv', 'Lib', 'site-packages')
if os.path.exists(venv_site_pkgs) and venv_site_pkgs not in sys.path:
    sys.path.insert(0, venv_site_pkgs)

# 2. Setup Logging in the execution folder (not inside .venv)
log_path = os.path.join(base_dir, 'debug.log')
logging.basicConfig(
    filename=log_path, 
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Configuration ---
CAPTURE_ALL_TEXT = True
DISREGARD_LIST = ["the", "and", "http", "is", "this", "what", "a", "an"]
FLAG_GROUPS = {
    "Economy": ["economy"],
    "Interest": ["interest"],
    "Inflation": ["inflation"],
    "Wealth": ["wealth"],
    "Stock": ["stock","dow jones","nasdaq","s&p"],
    "Mortgage": ["mortgage"],
    "Credit": ["credit"],
    "Dollar": ["dollar"],
    "Income": ["income"],
    "Job": ["job"],
    "Blackrock": ["blackrock"],
    "Blackstone": ["blackstone"],
    "Deficit": ["deficit"],
    "Private credit": ["private credit"],
    "Inequality": ["inequality"],
    "Petrodollar": ["petrodollar"],
    "Petroyuan": ["petroyuan"],
    "Tariff": ["tariff"],
    "Election": ["election", "voting", "voter","voters"],
    "Crime": ["criminal", "fraud", "allegation"],
    "Health": ["medicaid", "health"],
    "Tech": ["technology", "crypto"],
    "Minnesota": ["minnesota"],
    "China": ["china"],
    "Israel": ["israel","jewish"],
    "Iran": ["iran"],
    "US": ["america", "u.s.a.","u.s."],
    "Canada": ["canada"],
    "Europe": ["europe"],
    "Venezuela": ["venezuela"],
    "Trump": ["trump"],
    "Nuke": ["Nuke", "Nuclear"],
    "President": ["president"],
    "Republican": ["republican"],
    "Democrat": ["democrat"],
    "Military": ["military"],
    "Newsom": ["Newsom"],
    "Crypto": ["crypto"],
    "NSPM": ["nspm"],
    "Epstien": ["epstien"],
    "Constitution": ["constitution"],
    "AI": ["GPT","Gemini","Claude"]
}
BIG_WORDS = {
    "Shadowbank": ["shadow banking","shadow bank","shadowbank","shadowbanking"],
    "Blackrock": ["black rock"],
    "Blackstone": ["black stone"],
    "Red State": ["red states", "red state"],
    "US": ["united states"],
    "Blue States": ["blue states", "blue state"]
}
SHORT_FLAGS = {
    "AI": ["AI"],
    "ICE": ["ICE"],
    "Military": ["War"],
    "Oil": ["Oil"],
    "US": ["USA"]
}

# --- Filtering Logic ---

def filter_text_with_categories(text_list):
    flagged_data = [] # Stores (original_text, category)
    year_pattern = r"\b(19\d{2}|20\d{2}|2100)\b"
    full_image_text = " ".join(text_list).lower()
    for category, words in BIG_WORDS.items():
            for word in words:
                if word.lower() in full_image_text:
                    flagged_data.append({
                        "text": f"Found {word}", 
                        "category": category
                    })
                    break
    for text in text_list:
        clean_text = text.lower().strip()
        found_category = None
        year_match = re.search(year_pattern, text)
        if year_match:
            found_category = year_match.group()
        if not found_category:
            for category, words in FLAG_GROUPS.items():
                if any(word.lower() in clean_text for word in words):
                    found_category = category
                    break
        if not found_category:
            for category, variations in SHORT_FLAGS.items():
                for word in variations:
                    short_match = re.search(rf"\b{re.escape(word.lower())}\b", clean_text)
                    if short_match:
                        found_category = category
                        break
                if found_category:
                    break
        if found_category:
            flagged_data.append({
                "text": text,
                "category": found_category
            })
            
    return flagged_data

def filter_text_to_clean_string(text_list):
    final_snippets = []
    
    for text in text_list:
        words = text.split()
        clean_words = [
            w for w in words 
            if w.lower().strip() not in DISREGARD_LIST 
            and not w.lower().startswith("http")
        ]
        if clean_words:
            final_snippets.append(" ".join(clean_words))
    return " | ".join(final_snippets)

def detect_chart(image_path):
    """Returns True if the image is likely a chart/graph."""
    img = Image.open(image_path).convert("RGB")
    input_tensor = CHART_TRANSFORM(img).unsqueeze(0)
    
    with torch.no_grad():
        output = CHART_MODEL(input_tensor)
    
    probabilities = torch.nn.functional.softmax(output[0], dim=0)
    # Check if 'chart' label is the highest probability
    chart_idx = CHART_LABELS.index('chart') if 'chart' in CHART_LABELS else 0
    return probabilities[chart_idx] > 0.5

# --- Helper Functions ---
def safe_imread(file_path):
    try:
        img_array = np.fromfile(file_path, dtype=np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    except Exception as e:
        logging.error(f"Safe imread failed for {file_path}: {e}")
        return None

def extract_text(image_path, reader):
    img = safe_imread(image_path)
    if img is None: return []
    try:
        return reader.readtext(img, detail=0)
    except Exception as e:
        logging.error(f"OCR failed: {e}")
        return []

def set_windows_metadata(file_path, title, comment):
    """Writes metadata using Wide String format, truncated to 2000 chars."""
    try:
        pythoncom.CoInitialize()
        ps = propsys.SHGetPropertyStoreFromParsingName(file_path, None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
        
        # Windows Title (Categories)
        if title:
            pk_title = propsys.PSGetPropertyKeyFromName("System.Title")
            ps.SetValue(pk_title, propsys.PROPVARIANTType(str(title), pythoncom.VT_LPWSTR))

        # Windows Comment (Flagged Text - limited to 2000 chars)
        if comment:
            pk_comment = propsys.PSGetPropertyKeyFromName("System.Comment")
            safe_comment = str(comment)[:2000]
            ps.SetValue(pk_comment, propsys.PROPVARIANTType(safe_comment, pythoncom.VT_LPWSTR))
        
        ps.Commit()
    except Exception as e:
        logging.error(f"Metadata error on {file_path}: {e}")
    finally:
        pythoncom.CoUninitialize()

# --- Main Process ---
def process_images(input_dir="images"):
    if not os.path.exists(input_dir):
        print(f"❌ Error: Folder '{input_dir}' not found.")
        return

    for filename in os.listdir(input_dir):
        if filename.lower().endswith((".jpg", ".png", ".jpeg")):
            image_path = os.path.abspath(os.path.join(input_dir, filename))
            print(f"🔍 Processing {filename}...")
            # --- NEW: Chart Detection Step ---
            is_chart = detect_chart(image_path)
            # 1. OCR Step
            text_raw = extract_text(image_path, EASYOCR_READER) 
            # 2. Get the flagged data packets
            flagged_items = filter_text_with_categories(text_raw)
            strip_text = filter_text_to_clean_string(text_raw)
            # 3. Handle Years for the Prefix
            # Grabs anything that is a 4-digit number (e.g., "1995")
            years = sorted(list(set(item['category'] for item in flagged_items if item['category'].isdigit())))
            year_prefix = f"[{', '.join(years)}] " if years else ""
            # 4. Handle Tags (Windows Title)
            # Filter OUT the years so the title only shows categories (Economy, AI, etc.)
            unique_categories = sorted(list(set(
                item['category'] for item in flagged_items if not item['category'].isdigit()
            )))
            # --- NEW: Add 'Chart' to tags if detected ---
            if is_chart:
                unique_categories.append("Chart")
                unique_categories = sorted(list(set(unique_categories)))    
            final_tags = ", ".join(unique_categories)
            # 5. Build the Comment
            # Prepend the year prefix to the combined text snippets
            final_comment = f"{year_prefix}{strip_text}"[:2000]
            # 6. Apply Metadata
            set_windows_metadata(image_path, final_tags, final_comment)
            # Console UI
            print(f"✅ Done: {filename}")
            if years or unique_categories:
                print(f"   Years: {', '.join(years) if years else 'None'}")
                print(f"   Tags: {final_tags if final_tags else 'None'}")
                preview = final_comment[:80] + "..." if len(final_comment) > 80 else final_comment
                print(f"   Comment: {preview}")
            else:
                print("   (No flags found)")
            print("-" * 30)

if __name__ == "__main__":
    process_images()