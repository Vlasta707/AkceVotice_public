# Skript v Pythonu, který opakovaně každou hodinu načte z API Open-Meteo teplotu a oblačnost na příštích 12 hodin a přidá je 
# do logovacího souboru CSV. Zároveň zapíše tyto údaje do bufferu včetně časové značky a tím v bufferu přepíše údaj předchozí.

# Při chybě spojení se zachová takto:
# - *Chyba spojení:* Jakmile nastane `ConnectionResetError` (nebo jakákoliv jiná chyba při stahování dat z Open-Meteo), 
#    program skočí do sekce `except`.
# - *Výpis chyby:* Na mail mereni.teploty@seznam.cz pošle zprávu o chybě. Není to kompletní zpráva o chybě,pouze část 
#    do prvního otazníku, aby se v ní případně uživateli nezobrazil můj API-klíč. Pokud nejde ani odeslat mail 
#    (třeba nejde internet), vypíše se chybové hlášení alespoň na terminál.
# - *Čekání:* Příkaz `time.sleep(600)` zastaví vykonávání funkce na přesně **10 minut**.
# - *Restart:* Po uplynutí 10 minut zavolá funkce samu sebe (cyklus `while not uspech`), což znamená, že skočí zpět na svůj začátek 
#    a zkusí data stáhnout znovu. Pokud opět není vše vpořádku, už se neposílá žádný další mail.
# - *Návrat k plánu:* Jakmile se data jednou úspěšně stáhnou, funkce se dokončí a odešle se email "OPRAVENO: Skript Počasí". 
#    Hlavní smyčka `while True` dál čeká na další celou hodinu podle plánovače `schedule`.

# Klíčové vlastnosti programu:
# - *Struktura `try-except`*: Skript nespadne při první chybě na internetu, což je nejčastější důvod selhání skriptů běžících na pozadí.
#    Skript pošle při prvním výskytu chyby email o chybě na adresu mereni.teploty@seznam.cz a každých 10 minut bude zkoušet,
#    jestli už komunikace s Open-Meteo běží. Při dlouhodobé chybě tak přijde jen první email o chybě a pak až email o opravě chyby.
# - *Oddělení konfigurace*: Všechny důležité hodnoty (souřadnice, e-mail) jsou na začátku. 
#    Není třeba hledat v celém kódu, co přepsat.
# - *Čitelnost CSV*: Použití `utf-8-sig` a středníku jako oddělovače zaručuje, že když soubor otevřete v českém Excelu, 
#    uvidíte správně diakritiku i rozdělení do sloupců.
#   *Bezpečnost*: Ořezávání chybové hlášky před prvním otazníkem je pokročilá technika, která chrání hesla nebo API klíče 
#    před nechtěným odesláním v těle e-mailu.
# - *Žádné duplicity:* Plánovač `schedule` počká, dokud funkce `moje_predpoved` neskončí. 
#    Takže se nestane, že by se pokusy o stažení začaly „překrývat“.
# - *Čistota:* Použití `while not uspech` je bezpečnější pro paměť počítače než rekurze (volání funkce uvnitř sebe sama), 
#    zejména pokud by výpadek trval hodně dlouho.
# - *`except (KeyboardInterrupt, SystemExit): raise`*: Tohle je klíčová část. Říká Pythonu: „Pokud uživatel zmáčkne Ctrl+C, 
#    nepovažuj to za chybu sítě, nic nevypisuj a okamžitě ukonči tuhle smyčku.“
#    Díky tomu skript zareaguje na Ctrl+C i uprostřed těch 10 minut čekání – nebude muset čekat na konec časového limitu.

# --- POUŽITÉ KNIHOVNY ---

import requests      # Knihovna pro odesílání požadavků na internet (stahování dat z API)
import csv           # Modul, který umí správně formátovat a zapisovat soubory .csv
import schedule      # Šikovný plánovač, který hlídá, kdy je "celá hodina"
import time          # Knihovna pro práci s časem (používáme ji pro pauzy/čekání)
import smtplib       # Protokol, který umožňuje Pythonu připojit se k e-mailovému serveru
import os            # Knihovna pro práci s operačním systémem (kontrola existence souborů)
from email.mime.text import MIMEText     # Pomůcka pro správné sestavení těla e-mailu
from datetime import datetime            # Knihovna pro zjištění aktuálního data a času

# --- NOVÉ: Načítání skrytých údajů ---
try:
    from dotenv import load_dotenv       # Importujeme funkci pro načtení .env souboru
    load_dotenv()                        # Tato funkce vyhledá soubor .env a "vytáhne" z něj data
except ImportError:
    # Pokud by knihovna nebyla nainstalovaná, program bude hledat v systému
    pass

# --- 1. KONFIGURACE ---
# Proměnné jsou na začátku, aby se daly snadno změnit na jednom místě.

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

def posli_email(predmet, text):
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

        # 'with' zajistí, že se spojení se serverem po odeslání samo bezpečně ukončí
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_ODESILATEL, EMAIL_HESLO) # Přihlášení k účtu
            server.send_message(msg)                    # Samotné odeslání
        print(f"📧 E-mail odeslán: {predmet}")
    except Exception as e:
        # Pokud nejde ani odeslat mail (třeba nejde internet), vypíšeme to aspoň na obrazovku
        print(f"❌ Chyba při odesílání e-mailu: {e}")

# --- 3. HLAVNÍ FUNKCE MĚŘENÍ ---

def moje_predpoved():
    """Stáhne data, uloží je do obou CSV souborů a v případě chyby zkouší restart."""
    global chyba_oznamena # Říkáme Pythonu, že chceme měnit flag
    uspech = False        # Na začátku předpokládáme, že se to ještě nepovedlo
    
    # Cyklus 'while not uspech' běží tak dlouho, dokud se data úspěšně nestáhnou z Open-Meteo
    while not uspech:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Spouštím aktualizaci (Open-Meteo)...")
        
        try:
            # 1. STAŽENÍ DAT: requests.get pošle dotaz na web. Timeout 15s zabrání nekonečnému čekání.
            # Pokud ve složce existuje soubor 'vyvolej_chybu.txt', nastavíme timeout na 0.001s (vyvolá chybu pro testování)
            testovaci_timeout = 0.001 if os.path.exists("vyvolej_chybu.txt") else 15
            response = requests.get(URL, timeout=testovaci_timeout)
            response.raise_for_status() # Pokud web vrátí chybu (např. 404), skočí to rovnou do 'except'
            data = response.json()      # Převede stažený text do formátu, kterému Python rozumí (slovník)

            # 2. ZPRACOVÁNÍ: Vytáhneme si ze stažených dat jen ty seznamy, které nás zajímají
            hodiny = data['hourly']['time']
            teploty = data['hourly']['temperature_2m']
            mraky = data['hourly']['cloud_cover']
            
            # Zjistíme, jaký je právě čas v ISO formátu (např. 2026-04-14T10:00)
            ted_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
            
            # Najdeme, na kterém místě (indexu) v seznamu od API je aktuální hodina
            try:
                aktualni_hodina_index = hodiny.index(ted_iso)
            except ValueError:
                # Pokud by se čas neshodoval, jako zálohu vezmeme aktuální hodinu v dni
                aktualni_hodina_index = datetime.now().hour
            
            # Vyřízneme přesně 12 záznamů od aktuální hodiny dál (tzv. "slicing")
            vyber_casu = hodiny[aktualni_hodina_index : aktualni_hodina_index + 12]
            vyber_teplot = teploty[aktualni_hodina_index : aktualni_hodina_index + 12]
            vyber_mraku = mraky[aktualni_hodina_index : aktualni_hodina_index + 12]
            
            # Úprava pro hezký vzhled v logovacím CSV (přidání jednotek)
            headers = [t.split('T')[1] for t in vyber_casu] # Z "T14:00" udělá jen "14:00"
            row_temp_hist = [f"{t} °C" for t in vyber_teplot]
            row_clouds_hist = [f"{c} %" for c in vyber_mraku]

            # --- 3a. ZÁPIS DO LOGOVACÍHO SOUBORU (Mód 'a' = append, přidat na konec) ---
            with open(CSV_FILE, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';') # Používáme středník (český Excel ho má rád)
                now_str = datetime.now().strftime("%d.%m. %H:%M")
                writer.writerow([f"--- Předpověď vytvořena: {now_str} ---"])
                writer.writerow(["Parametr"] + headers)
                writer.writerow(["Teplota"] + row_temp_hist)
                writer.writerow(["Oblačnost"] + row_clouds_hist)
                writer.writerow([]) # Prázdný řádek pro oddělení dalších hodin
            
            # --- 3b. ZÁPIS DO BUFFERU (Mód 'w' = write, smazat a zapsat znovu) ---
            # Vytvoříme jeden dlouhý seznam o 25 prvcích (Čas + 12x Teplota + 12x Oblačnost)
            buffer_data = [datetime.now().strftime("%H:%M:%S")] + vyber_teplot + vyber_mraku

            with open(BUFFER_FILE, 'w', newline='', encoding='utf-8-sig') as f_buf:
                writer_buf = csv.writer(f_buf, delimiter=';')
                writer_buf.writerow(buffer_data) # Zapíše jen ten jeden jediný řádek

            print(f"✅ Data úspěšně uložena.")

            # Pokud byla předtím chyba, pošleme e-mail, že už je to v pořádku
            if chyba_oznamena:
                posli_email("OPRAVENO: Skript Počasí", f"Spojení obnoveno v {datetime.now().strftime('%H:%M:%S')}.")
                chyba_oznamena = False # Nastavíme zpět na False pro případnou další chybu
            
            uspech = True # Tímto ukončíme vnitřní cyklus 'while' a funkce skončí

        except (KeyboardInterrupt, SystemExit):
            # Pokud uživatel zmáčkne Ctrl+C, program se nesmí snažit o restart, ale musí skončit
            raise 
        except Exception as e:
            # Sem program skočí, pokud nastane jakákoliv chyba (např. vypadne Wi-Fi)
            zprava_chyby = str(e)
            # Ochrana soukromí: Pokud chyba obsahuje otazník (URL parametry), uřízneme ji tam, aby do emailu neunikl API klíč
            bezpecna_zprava = zprava_chyby.split('?')[0] if '?' in zprava_chyby else zprava_chyby
            print(f"⚠️ Chyba: {bezpecna_zprava}")
            
            # Pokud je to první chyba v řadě, pošleme o tom e-mail
            if not chyba_oznamena:
                posli_email("CHYBA: Skript Počasí", f"Chyba při stahování dat.\nDetail: {bezpecna_zprava}")
                chyba_oznamena = True
            
            # Počkáme 10 minut a pak 'while' cyklus zkusí stáhnout data znovu (restart funkce)
            print("⏳ Zkusím to znovu za 10 minut...")
            time.sleep(600)

# --- 4. PLÁNOVAČ A HLAVNÍ SMYČKA ---

try:
    # 1. Spuštění hned po zapnutí, abychom nečekali hodinu na první data
    moje_predpoved()

    # 2. Naplánování: Spustit funkci 'moje_predpoved' v každou celou hodinu (např. 14:00, 15:00...)
    schedule.every().hour.at(":00").do(moje_predpoved)

    print("-" * 45)
    print("Sledování Open-Meteo běží na pozadí.")
    print(f"Zápis do: {CSV_FILE} a {BUFFER_FILE}")
    print("Ukončíte klávesami Ctrl+C.")
    print("-" * 45)

    # 3. Nekonečná smyčka, která udržuje skript naživu
    while True:
        schedule.run_pending() # Zkontroluje, jestli už není "celá hodina"
        time.sleep(1)          # Aby procesor zbytečně nepracoval na 100%, počkáme vteřinu

except KeyboardInterrupt:
    # Hezké ukončení programu po stisknutí Ctrl+C
    print("\nProgram byl ukončen uživatelem.")