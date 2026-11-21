# Tron Wallet Analyse

Een gratis tool om verbanden tussen Tron wallets zichtbaar te maken. Je geeft meerdere wallets in, de tool volgt USDT (TRC20) en TRX transfers en toont in een interactieve grafiek of de wallets direct of indirect met elkaar verbonden zijn.

Gebaseerd op de werkwijze van onchain onderzoekers: geld volgen, gedeelde tegenpartijen zoeken en kijken wie een wallet oorspronkelijk van TRX voorzag.

## Wat het doet

* **Meerdere wallets tegelijk** analyseren, elk met een eigen naam
* **Directe en indirecte verbanden** vinden tot meerdere hops diep
* **Gedeelde funder** detecteren: wie stuurde de eerste TRX naar een wallet (vaak het sterkste bewijs dat wallets bij dezelfde persoon horen)
* **Exchanges herkennen**: drukke adressen worden niet verder gevolgd en verbanden via exchanges worden als zwak gemarkeerd
* **Spamfilter** tegen kleine transfers en address poisoning
* **Interactieve grafiek** in je browser met bedragen op de lijnen, legende en samenvatting
* **Tekstrapport** met de exacte route, bedragen en data per verband

## Installatie

Vereist: Python 3.10 of hoger.

**Windows (makkelijkst):** dubbelklik op `start.bat`. De eerste keer maakt die een virtuele omgeving aan en installeert alles.

**Handmatig:**

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
python gui.py
```

## API key (gratis)

De tool gebruikt de TronGrid API. Zonder key werkt het ook, maar veel trager.

1. Maak een account op [trongrid.io](https://www.trongrid.io)
2. Ga in het dashboard naar **API Keys** en klik op **Create API Key**
3. Plak de key in de GUI, of zet hem als omgevingsvariabele:

```powershell
$env:TRONGRID_API_KEY="jouw-key"
```

Vink je "key onthouden" aan, dan wordt hij lokaal opgeslagen in `config.json`. Dat bestand staat in `.gitignore` en komt nooit in je repository.

## Gebruik

### GUI

Zet per lijn een naam en een adres, gescheiden door een komma:

```
Wallet A, TXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
Wallet B, TYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYYY
TZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ
```

De naam mag ook weg. Klik op **Start analyse**. Als het klaar is, opent de grafiek automatisch. Alle resultaten komen met datum in de map `resultaten/`.

### Command line

```bash
python tron_links.py TXXX... TYYY... --depth 2
python tron_links.py --file wallets.txt --max-addr 200
```

| Optie | Standaard | Uitleg |
|---|---|---|
| `--depth` | 2 | Hoeveel hops diep zoeken |
| `--max-addr` | 120 | Maximum aantal adressen om op te halen |
| `--top` | 15 | Per adres de N belangrijkste tegenpartijen volgen |
| `--hub-limit` | 60 | Vanaf hoeveel tegenpartijen een adres als exchange geldt |
| `--min-usdt` | 1 | Kleinere USDT transfers negeren |
| `--min-trx` | 0.5 | Kleinere TRX transfers negeren |
| `--alles` | uit | Alle tegenpartijen tonen in plaats van alleen verbanden |

## De grafiek lezen

| Vorm | Betekenis |
|---|---|
| Rood blok met naam | Jouw wallet |
| Paarse ruit | Funder (stuurde de eerste TRX) |
| Oranje bol | Adres op een verbindingspad |
| Grijs vierkant | Druk adres, waarschijnlijk exchange of dienst |
| Groene lijn | USDT transfer |
| Blauwe lijn | Alleen TRX |
| Oranje lijn | Kortste verbinding tussen twee van jouw wallets |

Hover over een node of lijn voor details en een link naar Tronscan. Nodes kun je verslepen.

**STERK** betekent een verbinding zonder exchanges ertussen. **ZWAK** betekent dat de enige route via een druk adres loopt. Dat zegt meestal weinig, omdat veel mensen dezelfde exchange gebruiken.

## Beperkingen

* Alleen het Tron netwerk (TRX en USDT TRC20)
* Geen labels van exchanges: controleer grijze adressen zelf via [Arkham](https://intel.arkm.com) of [Tronscan](https://tronscan.org)
* Een verband is een aanwijzing, geen bewijs. Controleer bevindingen altijd handmatig.
* Diepere zoekopdrachten vragen veel API calls en duren langer

## Disclaimer

Deze tool gebruikt alleen publiek beschikbare blockchaindata en is bedoeld voor educatief en onderzoeksgebruik. Gebruik hem verantwoord en respecteer de privacy van anderen.
