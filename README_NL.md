# Garmin Training Bridge – korte handleiding

Deze software kopieert Garmin-hardloopgegevens naar een **aparte privé-GitHub-repository**. De code kun je openbaar delen, maar de persoonlijke trainingsgegevens niet.

## Zo kan iemand anders dit gebruiken

1. Maak via https://github.com/new een **lege PRIVATE repository** aan voor de eigen Garmin-gegevens.
2. Download dit codepakket (of gebruik de openbare GitHub-template).
3. Installeer Python 3.12 of nieuwer en GitHub CLI (`gh`). Op een Mac met Homebrew: `brew install gh`.
4. Start `01_INSTALL.command`. Vul bij de vragen uitsluitend **de eigen** `GitHub-gebruikersnaam/repository` in.
5. Start `02_FIRST_SYNC.command`. Log lokaal in bij Garmin en GitHub (eventueel tweestapsverificatie).
6. Controleer de PRIVATE gegevensrepository. Start `03_ENABLE_DAILY.command` voor dagelijkse synchronisatie.
7. Voor oude trainingen: gebruik `05_DOWNLOAD_HISTORY.command` en daarna opnieuw `02_FIRST_SYNC.command`.

**Privacy:** de datarepository blijft private; Garmin-wachtwoorden, tokens, routes en originele FIT/TCX/GPX-bestanden worden niet geüpload. Hartslag, activiteiten-datums en Garmin-IDs zijn nog wel persoonsgegevens. Laat oude gegevens en privacyrechten nakijken voordat je iemand toegang geeft.

**Belangrijk:** maak deze **code** publiek via een nieuwe repository. Maak nooit een bestaande repository met je persoonlijke trainingsgegevens publiek; eerdere commits kunnen die gegevens blijven bevatten.

Zie [README.md](README.md) voor de volledige technische en veiligheidsinstructies.
