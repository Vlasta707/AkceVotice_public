"""
Skript pro pravidelné stahování předpovědi počasí (teplota, oblačnost) z API Open-Meteo.
Výstupy se ukládají do historie (CSV) a do bufferu s aktuálním přehledem pro další zpracování.

Logika ošetření chyb a automatického obnovení:
- Odolnost: Program nespadne při výpadku sítě, zachytí výjimku a pokusí se o restart.
- Notifikace: Na e-mail odesílatele (z .env) pošle první zprávu o chybě. Hláška je ořezána 
  před parametry URL (?), aby nedošlo k nechtěnému úniku API klíčů v těle e-mailu.
- Retry cyklus: Skript čeká 10 minut a poté zkusí data stáhnout znovu. Během trvajícího 
  výpadku se další e-maily neposílají, aby nedošlo k zahlcení schránky uživatele.
- Obnova: Po úspěšném obnovení spojení odešle e-mail "OPRAVENO" a pokračuje v plánu.

Hlavní technické vlastnosti:
- Robustnost: Komplexní try-except bloky zajišťují stabilní běh na pozadí bez nutnosti dozoru.
- Konfigurovatelnost: Veškeré nastavení (souřadnice, SMTP) je centralizováno nebo načítáno z .env.
- Bezpečnost: Citlivé údaje jsou uloženy v externím .env souboru (nejsou přímo v kódu).
- Kompatibilita CSV: Použití 'utf-8-sig' a středníku zaručuje správné zobrazení v Excelu.
- Plánování úloh: Knihovna 'schedule' zajišťuje spouštění v přesně definované intervaly.
- Efektivita: Místo rekurze je použit cyklus, což je šetrnější k systémovým prostředkům.
- Responzivita: Ošetření 'KeyboardInterrupt' umožňuje čisté ukončení (Ctrl+C) i během čekání.
"""

# --- POUŽITÉ KNIHOVNY ---

import requests      # Pro stahování dat z webových API (např. Open-Meteo)
import csv           # Pro práci se soubory CSV (Comma Separated Values)
import schedule      # Pro plánování úloh v pravidelných intervalech (např. každou hodinu)
import time          # Pro práci s časem, například pro pozastavení programu (sleep)
import smtplib       # Pro odesílání e-mailů přes SMTP server
import os            # Pro interakci s operačním systémem (např. kontrola souborů, proměnné prostředí)
from email.mime.text import MIMEText     # Pomáhá správně formátovat text e-mailu
from datetime import datetime            # Pro práci s datem a časem (např. získání aktuálního času)
from dotenv import load_dotenv           # Pro načítání proměnných prostředí ze souboru .env

# --- NAČTENÍ KONFIGURACE Z .ENV SOUBORU ---
# Tento blok kódu zajistí, že citlivé údaje (jako hesla k e-mailu) nebudou přímo v kódu,
# ale v samostatném souboru .env. To je dobrá bezpečnostní praxe.

# os.path.abspath(__file__) vrátí celou cestu k tomuto souboru (VZT201_Meteo.py).
# os.path.dirname() pak z této cesty získá pouze adresář, ve kterém se soubor nachází.
# To nám umožní najít soubor .env, i když skript spustíme z jiného adresáře.
adresar_skriptu = os.path.dirname(os.path.abspath(__file__))
cesta_k_env = os.path.join(adresar_skriptu, '.env')

if os.path.exists(cesta_k_env):
    load_dotenv(cesta_k_env)
    # Pro tvou kontrolu (později můžeš tyto dva řádky smazat):
    print(f"✅ Soubor .env nalezen v: {adresar_skriptu}")
    print(f"📧 Načtený uživatel: {os.getenv('EMAIL_USER')}")
else:
    print(f"❌ CHYBA: Soubor .env nebyl nalezen v {adresar_skriptu}!")

# --- HLAVNÍ KONFIGURACE SKRIPTU ---
# Zde jsou definovány klíčové proměnné, které můžete snadno upravit.

LAT = "50.08"  # Zeměpisná šířka (Praha)
LON = "14.42"  # Zeměpisná délka (Praha)

# URL adresa: složený řetězec, který říká webu Open-Meteo, co přesně chceme a nastavení pro 2 dny (aby to vidělo přes půlnoc)
URL = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&hourly=temperature_2m,cloud_cover&forecast_days=2"

CSV_FILE = 'historie_pocasi.csv'     # Název logovacího souboru, kam se data neustále přidávají
BUFFER_FILE = 'buffer_pocasi.csv'    # Název souboru, který se vždy přepíše (obsahuje jen 25 údajů)

# Přihlašovací údaje pro e-mailový server Seznam.cz
# MODIFIKACE: Místo textu s heslem používáme os.getenv, který si heslo "vypůjčí" ze souboru .env
EMAIL_ODESILATEL = os.getenv("EMAIL_USER")     # Načte EMAIL_USER ze souboru .env
EMAIL_HESLO = os.getenv("EMAIL_PASSWORD")      # Načte EMAIL_PASSWORD ze souboru .env
EMAIL_PRIJEMCE = os.getenv("EMAIL_USER")       # Znovu použijeme načtený e-mail
SMTP_SERVER = "smtp.seznam.cz"
SMTP_PORT = 465  # Port 465 se používá pro zabezpečené spojení SSL

# Tato proměnná (tzv. flag) hlídá, jestli už byl odeslán mail o chybě.
# Zabrání tomu, aby při dlouhodobém výpadku internetu přišlo velké množství mailů.
chyba_oznamena = False 

# --- 2. FUNKCE PRO E-MAIL ---

def posli_email(predmet: str, text: str):
    """Tato funkce vezme předmět a text a odešle je přes server Seznamu."""
    # Kontrola pro začátečníky: Pokud se nepodařilo načíst heslo z .env, funkci ukončíme s varováním
    if not EMAIL_HESLO:
        print("❌ Chyba: Chybí heslo! Zkontrolujte soubor .env")
        return

    try:
        # Vytvoření objektu e-mailu a nastavení jeho hlaviček
        msg = MIMEText(text)
        msg['Subject'] = predmet
        msg['From'] = EMAIL_ODESILATEL
        msg['To'] = EMAIL_PRIJEMCE

        # 'with' příkaz zajistí, že se spojení se serverem po odeslání e-mailu automaticky a bezpečně uzavře.
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ODESILATEL, EMAIL_HESLO) # Přihlášení k e-mailovému účtu
            server.send_message(msg)                    # Odeslání připravené zprávy
        print(f"📧 E-mail odeslán: {predmet}")
    except Exception as e:
        # Pokud nejde ani odeslat mail (třeba nejde internet), vypíšeme to aspoň na obrazovku
        print(f"❌ Chyba při odesílání e-mailu: {e}")

# --- 3. HLAVNÍ FUNKCE MĚŘENÍ ---

def moje_predpoved():
    """
    Stáhne data o počasí z Open-Meteo API, zpracuje je, uloží do CSV souborů
    a v případě chyby se pokusí o opakování.
    """
    # Klíčové slovo 'global' říká, že chceme pracovat s proměnnou 'chyba_oznamena',
    # která je definována mimo tuto funkci (globálně).
    global chyba_oznamena 
    uspech = False        # Tato proměnná sleduje, zda se stahování a zpracování dat podařilo.
    
    # Cyklus 'while not uspech' se opakuje tak dlouho, dokud se data úspěšně nestáhnou a nezpracují.
    while not uspech:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Spouštím aktualizaci (Open-Meteo)...")
        
        try:
            # 1. STAŽENÍ DAT: requests.get odešle požadavek na webové API.
            # 'timeout=15' znamená, že skript bude čekat maximálně 15 sekund na odpověď.
            # Speciální podmínka s 'vyvolej_chybu.txt' slouží pro testování chybového stavu:
            # pokud soubor existuje, timeout se nastaví na velmi krátkou dobu, což uměle vyvolá chybu.
            testovaci_timeout = 0.001 if os.path.exists("vyvolej_chybu.txt") else 15
            response = requests.get(URL, timeout=testovaci_timeout)
            # Metoda raise_for_status() zkontroluje, zda server vrátil chybu (např. 404 Not Found, 500 Server Error).
            # Pokud ano, vyvolá výjimku, která je zachycena v bloku 'except'.
            response.raise_for_status() 
            data = response.json()      # Převede staženou odpověď (text ve formátu JSON) na Python slovník.

            # 2. ZPRACOVÁNÍ: Vytáhneme si ze stažených dat jen ty seznamy, které nás zajímají
            hodiny = data['hourly']['time']
            teploty = data['hourly']['temperature_2m']
            mraky = data['hourly']['cloud_cover']
            
            # Zjistíme aktuální čas a převedeme ho do formátu ISO 8601 (např. "2026-04-14T10:00").
            ted_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
            
            # Najdeme, na kterém místě (indexu) v seznamu od API je aktuální hodina
            try:
                aktualni_hodina_index = hodiny.index(ted_iso)
            except ValueError:
                # Pokud by se čas neshodoval, jako zálohu vezmeme aktuální hodinu v dni
                aktualni_hodina_index = datetime.now().hour

            # Získání 12 záznamů (hodin) od aktuálního času pomocí "slicingu" seznamů.
            # Slicing je způsob, jak vybrat část seznamu: [začátek : konec].
            vyber_casu = hodiny[aktualni_hodina_index : aktualni_hodina_index + 12]
            vyber_teplot = teploty[aktualni_hodina_index : aktualni_hodina_index + 12]
            vyber_mraku = mraky[aktualni_hodina_index : aktualni_hodina_index + 12]
            
            # Příprava dat pro CSV soubor:
            # Z časových řetězců (např. "2026-04-14T14:00") extrahujeme pouze hodiny (např. "14:00").
            headers = [t.split('T')[1] for t in vyber_casu] 
            row_temp_hist = [f"{t} °C" for t in vyber_teplot]   # Přidáme jednotky k teplotám
            row_clouds_hist = [f"{c} %" for c in vyber_mraku]   # Přidáme jednotky k oblačnosti

            # --- 3a. ZÁPIS DO LOGOVACÍHO SOUBORU (Mód 'a' = append, přidat na konec) ---
            # Otevření souboru v režimu 'a' (append) znamená, že se nová data přidají na konec souboru.
            # 'newline=' zabraňuje prázdným řádkům v CSV. 'utf-8-sig' zajišťuje správné zobrazení diakritiky v Excelu.
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';') # Vytvoření CSV zapisovače, jako oddělovač používáme středník.
                now_str = datetime.now().strftime("%d.%m. %H:%M")
                writer.writerow([f"--- Předpověď vytvořena: {now_str} ---"]) # Zápis hlavičky s časem vytvoření
                writer.writerow(["Parametr"] + headers)
                writer.writerow(["Teplota"] + row_temp_hist)
                writer.writerow(["Oblačnost"] + row_clouds_hist)
                writer.writerow([]) # Prázdný řádek pro oddělení dalších hodin
            
            # --- 3b. ZÁPIS DO BUFFERU (Mód 'w' = write, smazat a zapsat znovu) ---
            # Vytvoříme jeden dlouhý seznam o 25 prvcích (Čas + 12x Teplota + 12x Oblačnost)
            buffer_data = [datetime.now().strftime("%H:%M:%S")] + vyber_teplot + vyber_mraku 

            # Otevření souboru v režimu 'w' (write) znamená, že se obsah souboru vždy přepíše.
            with open(BUFFER_FILE, 'w', newline='', encoding='utf-8-sig') as f_buf:
                writer_buf = csv.writer(f_buf, delimiter=';')
                writer_buf.writerow(buffer_data) # Zapíše připravený řádek do bufferu.

            print(f"✅ Data úspěšně uložena.")

            # Pokud byla předchozí operace chybová (a e-mail o chybě byl odeslán),
            # nyní pošleme e-mail o tom, že se situace napravila.
            if chyba_oznamena:
                posli_email("OPRAVENO: Skript Počasí", f"Spojení obnoveno v {datetime.now().strftime('%H:%M:%S')}.")
                chyba_oznamena = False # Resetujeme flag, aby se při další chybě opět odeslal e-mail.
            
            uspech = True # Nastavíme na True, čímž ukončíme cyklus 'while not uspech'.

        except (KeyboardInterrupt, SystemExit):
            # Tato část zachytí stisk Ctrl+C (KeyboardInterrupt) nebo systémové ukončení.
            # 'raise' zajistí, že se program okamžitě ukončí, aniž by se pokoušel o restart nebo čekání.
            raise 
        except Exception as e:
            # Sem se dostaneme, pokud nastane jakákoliv jiná chyba (např. výpadek internetu, chyba API).
            zprava_chyby = str(e)
            # Důležitá ochrana soukromí: Pokud chybová zpráva obsahuje otazník (což by mohlo znamenat
            # únik citlivých URL parametrů nebo API klíčů), zprávu ořízneme, aby se tyto informace
            # nedostaly do e-mailu.
            bezpecna_zprava = zprava_chyby.split('?')[0] if '?' in zprava_chyby else zprava_chyby
            print(f"⚠️ Chyba: {bezpecna_zprava}")
            
            # Pokud je to první chyba v řadě (chyba_oznamena je False), pošleme o tom e-mail.
            if not chyba_oznamena:
                posli_email("CHYBA: Skript Počasí", f"Chyba při stahování dat.\nDetail: {bezpecna_zprava}")
                chyba_oznamena = True
            
            # Počkáme 10 minut (600 sekund) a pak se cyklus 'while not uspech' pokusí stáhnout data znovu.
            print("⏳ Zkusím to znovu za 10 minut...")
            time.sleep(600)

# --- 4. PLÁNOVAČ A HLAVNÍ SMYČKA ---

try:
    # 1. Spuštění hned po zapnutí, abychom nečekali hodinu na první data
    moje_predpoved() 

    # 2. Naplánování: Funkce 'moje_predpoved' se bude spouštět každou celou hodinu,
    # přesně v nulté minutě (např. 14:00, 15:00 atd.).
    schedule.every().hour.at(":00").do(moje_predpoved)

    print("-" * 45)
    print("Sledování Open-Meteo běží na pozadí.")
    print(f"Zápis do: {CSV_FILE} a {BUFFER_FILE}")
    print("Pro ukončení programu stiskněte klávesy Ctrl+C.")
    print("-" * 45)

    # 3. Nekonečná smyčka, která neustále kontroluje, zda je čas spustit naplánované úlohy.
    while True:
        schedule.run_pending() # Zkontroluje, zda nějaká naplánovaná úloha čeká na spuštění.
        time.sleep(1)          # Krátká pauza, aby se zbytečně nezatěžoval procesor.

except KeyboardInterrupt:
    # Hezké ukončení programu po stisknutí Ctrl+C
    print("\nProgram byl ukončen uživatelem.")