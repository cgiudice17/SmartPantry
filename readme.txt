Prima volta soltanto:
Crea l’ambiente virtuale:   python3 -m venv venv
Installa:   pip install -r requirements.txt
Avvia MySQL:    sudo systemctl start mysql
Entra in MySQL: sudo mysql
Poi esegui:CREATE DATABASE IF NOT EXISTS smart_pantry;

CREATE USER IF NOT EXISTS 'smart_user'@'localhost' IDENTIFIED BY 'smartpass';

GRANT ALL PRIVILEGES ON smart_pantry.* TO 'smart_user'@'localhost';

FLUSH PRIVILEGES;

EXIT;
Importa il db:mysql -u smart_user -p smart_pantry < smart_pantry.sql (password:smartpass)
Ogni volta che vuoi avviare il progetto:
Terminale 1 — avvia MySQL
Apri un terminale e scrivi: sudo systemctl start mysql

Poi puoi chiudere questo terminale oppure lasciarlo aperto.

2. Terminale 2 — avvia il backend Flask
Apri un nuovo terminale e scrivi:
cd ~/smart_pantry
source venv/bin/activate
python3 app.py

Deve uscire:    Running on http://127.0.0.1:5000
Questo terminale devi lasciarlo aperto.

3. Terminale 3 — avvia il sito HTML
Apri un altro terminale e scrivi:
cd ~/smart_pantry
source venv/bin/activate
python3 -m http.server 8000

Deve uscire:    Serving HTTP on 0.0.0.0 port 8000
Anche questo terminale devi lasciarlo aperto.
Serve per il sito.

4. Apri Google Chrome
vai su:
http://localhost:8000
