# Messenger-arkivet

En lokal webbapp som gör Facebooks Messenger-export läsbar: importerar den till SQLite med
FTS5 och visar den som en modern chattapp — med fulltextsökning, tidslinje-navigering,
mediegalleri, statistik och bokmärken.

Byggd för att klara riktiga arkiv: 400 000 meddelanden över 19 år, enskilda konversationer med
60 000 meddelanden, tiotusentals bilder. Hanterar båda formaten Messenger levererar — "Download
your information" och den krypterade chattexporten — och syr ihop dem till en sammanhängande
tidslinje per konversation.

Allt kör i Docker. Ingenting installeras på värdmaskinen.

> **Din data lämnar aldrig maskinen och versionshanteras aldrig.** Hela `data/`-katalogen —
> databasen, de uppackade originalen och thumbnail-cachen — är gitignorerad. Repot innehåller bara
> kod.

---

## Kom igång

```bash
make up
```

Öppna **http://localhost:5183**. Första gången möts du av en setup-guide: dra in dina
zip-filer, så laddas de upp, packas upp och importeras.

> Facebook delar upp exporten i flera zip-filer — **en innehåller texten, de övriga bilderna**.
> Markera alla på en gång. Väljer du bara några får du en ofullständig historik eller trasiga
> bilder.

Portarna går att ändra: `API_PORT=8010 WEB_PORT=5183 make up`.

### Lägga till fler arkiv, eller börja om

Guiden når du senare via `+` i verktygsraden. Har du redan ett arkiv importerat får du välja:

- **Lägg till i nuvarande arkiv** — nytt innehåll läggs till, dubbletter slås ihop, bokmärken
  överlever.
- **Börja om från grunden** — raderar databasen **och de uppackade originalen i
  `./data/imported-conversations/`**. Att bara tömma databasen räcker inte: importen läser hela
  mappen, så allt gammalt skulle komma tillbaka direkt. Kräver en aktiv bekräftelse, och filerna går inte att få tillbaka utan en
  ny nedladdning från Facebook. Samma sak gäller `python -m app.importer --reset`.

### Genväg för stora arkiv

Zip-filerna är ofta flera gigabyte. Ligger de redan i projektmappen slipper du uppladdningen:

```bash
make import-all                                    # alla *.zip i projektroten
make import SRC="/host/del1.zip /host/del2.zip"    # utvalda filer
make import SRC=/host/your_facebook_activity       # redan uppackad mapp
```

`/host` är projektmappen monterad read-only i containern. Filer som läses därifrån raderas
aldrig — bara arkiv som laddats upp via guiden städas bort efter uppackning.

### Produktionsläge

```bash
make prod     # en enda container på http://localhost:8010
```

---

## Var saker hamnar

Allt appen äger ligger under `./data/`:

| Sökväg | Innehåll | Kan raderas? |
|---|---|---|
| `data/imported-conversations/` | **Originalen.** Foton, videor, ljud, PDF:er och käll-JSON. Appen serverar all media härifrån. | **Nej — det är den här du säkerhetskopierar** |
| `data/archive.db` | All text: meddelanden, sökindex, statistik, bokmärken | Ja, byggs om vid omimport |
| `data/thumbs/` | Genererade WebP-thumbnails | Ja, återskapas vid behov |
| `data/uploads/` | Zip under uppladdning | Töms automatiskt |

Databasen lagrar aldrig bildbytes, bara sökvägar. `make clean-db` rör bara databasfilerna och
aldrig dina original — men raderar du hela `./data/` försvinner även bilderna.

---

## Så funkar det

### Teckenkodningen

Facebooks JSON escapar varje **byte** som en egen `\uXXXX`-kodpunkt, så `Engström` kommer ut
som `EngstrÃ¶m`. [`encoding.py`](apps/backend/app/encoding.py) vänder på det med
`s.encode('latin-1').decode('utf-8')` — men bara när avkodningen lyckas hela vägen, annars
skulle korrekt svensk text som `Allmän` förstöras. Testerna låser fast båda riktningarna.

### Två exportformat

Messenger levererar historiken i två helt olika format, och appen tar emot båda:

- **Download your information** — `your_facebook_activity/`, en mapp per konversation. Innehåller
  allt fram till den dag chatten krypterades.
- **Krypterad chattexport** — en platt `<Namn>_<n>.json` per konversation plus en delad
  `media/`-mapp. Det enda stället meddelanden efter krypteringen finns.

Formatet detekteras ur zip-filens innehållsförteckning, och de packas upp till skilda rötter.
Konversationerna sys sedan ihop på deltagaruppsättning, så en chatt blir en sammanhängande
tidslinje trots att de två halvorna kommer ur olika exporter. Är matchningen tvetydig — två chattar
med samma person, eller en tråd vars motpart är okänd — skapas hellre en separat tråd än att
gissa fel.

### Delad exportrot

Alla zip-delar av *en* DYI-nedladdning packas upp till **samma** mapp. Facebook delar inte upp exporten efter datum
utan efter fil: i den uppmätta 6-delade exporten låg 306 konversationers bilder i en annan zip
än sin JSON. Egen mapp per arkiv hade gjort varenda en av dem oläsbar.

### Att hoppa i 58 000 meddelanden

Varje meddelande får en `seq` — sin absoluta position i tråden — vid importen. Frontend känner
trådens längd i förväg, så scrollbaren blir korrekt innan något laddats, och ett hopp till
"juli 2014" eller en sökträff blir en direkt `scrollToIndex(seq)`. Bara de sidor som ska målas
hämtas. Ett fönster mitt i den största tråden svarar på ~17 ms.

Mediegalleriet gör samma sak: `media/locate` räknar ut en bilds position med samma `ORDER BY`
som rutnätet målar i, så galleriet kan hoppa direkt till bild 3 000 av 4 457. Båda vyerna delar
sidladdningen i [`useSparsePages`](apps/frontend/src/hooks/useSparsePages.ts).

### Galleriet följer läsningen

Står du i juli 2017 i samtalet visar galleriet det som delades då. Chattvyn rapporterar
tidsstämpeln för det översta synliga meddelandet, galleriet slår upp närmaste bild via
`media/locate?ts=` och scrollar dit. Följningen pausas i fyra sekunder så fort du själv bläddrar
i galleriet — annars slåss de två om scrollpositionen. Chippen i galleriets huvud visar vilket
läge som gäller och stänger av följningen helt om du vill.

### Sökordning

Söker du på en person vill du hitta personen, inte alla grupper hen råkat vara med i.
Direktkonversationer rankas därför först, sedan grupper vars namn matchar, sist grupper där en
deltagare matchar; senaste aktivitet skiljer bara inom varje rang. Din egen medlemskap räknas
inte — du finns i varenda tråd, så utan det undantaget skulle en sökning på ditt eget namn
returnera hela arkivet.

### Emoji

FTS5:s `unicode61`-tokenizer behandlar emoji som avgränsare och indexerar dem aldrig. Emoji får
därför ett eget index, som också driver "mest använda emojis" i statistiken. `❤` och `❤️`
normaliseras till samma tecken, annars missar sökningen hälften av träffarna.

### Sökträffar kan inte injicera markup

`snippet()` returnerar osynliga sentineltecken i stället för `<mark>`. Frontend delar på dem och
renderar bitarna som textnoder — 19 år av chattinnehåll når aldrig DOM:en som HTML.

### Om- och tilläggsimport

Varje meddelande får en `dedupe_key` från sitt innehåll. Att importera om samma export, eller
lägga till nästa års export, konvergerar i stället för att duplicera — och `message.id` ligger
still, så bokmärken pekar rätt efteråt.

---

## Utveckling

```bash
make test      # 105 pytest-tester
make shell     # skal i api-containern
make db        # radräkning i databasen
make clean-db  # radera databasen (dina original rörs inte)
```

Struktur:

```
apps/backend/app/
├── encoding.py  emoji.py  db.py  schema.sql  deps.py
├── importer/    reader → parse → load → derive
└── routers/     threads  search  media  stats  bookmarks  admin

apps/frontend/src/
├── components/  Sidebar  ChatView  MessageBubble  SearchPanel  TimeTravel
│                MediaGallery  Lightbox  StatsDialog  BookmarksPanel  SetupWizard
└── hooks/       useThreadWindow
```

## Tangentbord

| Tangent | Gör |
|---|---|
| `⌘K` / `Ctrl+K` | Öppna sök |
| `Esc` | Stäng panel eller lightbox |
| `←` `→` | Bläddra i lightboxen |
