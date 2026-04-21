
```markdown
# Sledování počasí (Open-Meteo API)

Tento Python skript v pravidelných intervalech stahuje předpověď počasí (teplota, oblačnost) z API Open-Meteo pro zadané souřadnice a ukládá data do formátu CSV pro další analýzu.

## Hlavní funkce
- **Automatický sběr dat:** Každou hodinu uloží aktuální předpověď.
- **Odolnost vůči chybám:** Při výpadku internetu nebo API se skript neukončí, ale zkouší spojení obnovit.
- **E-mailové notifikace:** Při prvním výskytu chyby a následné opravě odešle informační e-mail.
- **Logování:** Ukládá historii do `historie_pocasi.csv` a aktuální stav do `buffer_pocasi.csv`.

## Požadavky
- Python 3.10+
- Knihovny uvedené v `requirements.txt`

## Instalace a nastavení

1. **Klonování repozitáře:**
   ```bash
   git clone <url-vašeho-repozitáře>
   cd TopPower_01_verejne
   ```

2. **Vytvoření virtuálního prostředí:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # V Linuxu/macOS
   # nebo venv\Scripts\activate ve Windows
   ```

3. **Instalace knihoven:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Konfigurace (Důležité):**
   Vytvořte v kořenové složce soubor `.env` a vložte do něj své přihlašovací údaje k e-mailu:
   ```text
   EMAIL_USER=vas-email@seznam.cz
   EMAIL_PASSWORD=vase-heslo-pro-aplikace
   ```
   *Poznámka: Pro Seznam.cz je nutné v nastavení účtu vygenerovat speciální "Heslo pro aplikace".*

## Spuštění
Skript spustíte příkazem:
```bash
python VZT201_Meteo.py
```
Skript běží na pozadí. Ukončíte jej stisknutím `Ctrl+C`.

## Soubory projektu
- `VZT201_Meteo.py`: Hlavní skript.
- `.env`: Konfigurační soubor (neveřejný, ignorován Gitem).
- `historie_pocasi.csv`: Kumulativní záznam měření.
- `buffer_pocasi.csv`: Poslední stažená data (vždy 1 řádek).
```
