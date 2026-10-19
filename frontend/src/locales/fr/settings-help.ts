// Help text of each setting on the Settings page, by key. English is the comment above it in .env.example; keep
// these in step when one changes. A missing key shows the English text.
export const settingsHelp: Record<string, string> = {
  TELEPHONY_PROVIDER:
    "D'où viennent les enregistrements et à quoi se connecte le softphone. Intégré : govoice. Un autre système téléphonique se branche en ajoutant un adaptateur dans call_analyzer/adapters/telephony/ (voir base.py). Redémarrez après modification.",
  GOVOICE_COOKIE:
    "Rempli automatiquement quand vous vous connectez à GoVoice depuis l'application (Paramètres > Se connecter à GoVoice). Ou collez-le à la main : DevTools > Réseau > la requête « Enregistrement » > l'en-tête « Cookie ».",
  GOVOICE_RECORDINGS_DIR:
    "Dossier qui sert les fichiers mp3. Laissez vide pour le détecter automatiquement depuis la page Enregistrement.",
  GOVOICE_VERIFY_SSL: "Mettez false si le serveur utilise un certificat auto-signé.",
  SOFTPHONE_WS_URL:
    "Passer et recevoir des appels GoVoice dans le navigateur. Chaque compte reçoit son poste et son identifiant GoVoice dans Utilisateurs ; l'identifiant et le mot de passe SIP sont récupérés depuis GoVoice avec cet identifiant. Le WebSocket WebRTC de GoVoice.",
  SOFTPHONE_DOMAIN: "Domaine SIP sur lequel les postes s'enregistrent.",
  SOFTPHONE_USER_PREFIX:
    "Placé devant le poste pour former l'identifiant SIP : le poste 100 se connecte en 1759512535_100. Vide : déduit de GOVOICE_RECORDINGS_DIR (govoice_enreg_1759512535).",
  SOFTPHONE_ICE_SERVERS:
    "Serveurs STUN/TURN pour l'audio des appels, séparés par des virgules. TURN avec identifiant : turn:user:password@host:3478",
  SECRET_KEY:
    "Clé qui chiffre les mots de passe enregistrés dans la base (identifiants du softphone). N'importe quel long texte aléatoire. Vide : une clé aléatoire est créée une fois dans data/secret.key (sauvegardez-la avec la base). La changer rend les mots de passe enregistrés illisibles.",
  RECORDING_CLOCK_OFFSET_MINUTES:
    "Les appels du poste sont associés à leurs enregistrements GoVoice par l'heure. Si l'horloge de GoVoice avance sur celle de ce serveur (par ex. serveur en UTC et GoVoice à l'heure tunisienne), la différence en minutes (par ex. 60 ; négative si elle retarde).",
  DESK_IDLE_PROMPT_MINUTES:
    "Un agent en prise d'appels qui reste au poste autant de minutes sans appeler personne est invité à appeler (à nouveau toutes les mêmes minutes tant que cela dure). Chaque relance est journalisée pour les admins (Opérations > KPI > Relances d'inactivité). 0 : désactivé.",
  DESK_EARNED_BREAK:
    "Pauses méritées : un agent qui clôture DESK_EARNED_BREAK_CALLS appels se voit proposer une pause de DESK_EARNED_BREAK_MINUTES (le compte repart après chaque pause prise). Elle est journalisée comme pause « Pause méritée », visible sur le tableau et les KPI.",
  ALERT_IDLE_MINUTES:
    "Alertes du tableau d'équipe (Opérations > Tableau d'équipe), 0 en désactive une. Un agent en prise d'appels mais inactif (aucun appel, un contact servi mais non composé, ou un appel en cours de clôture) depuis autant de minutes :",
  ALERT_LONG_CALL_MINUTES: "Un appel qui dure autant de minutes :",
  ALERT_NO_ANSWER_STREAK: "Autant d'appels sans réponse d'affilée pour un agent aujourd'hui :",
  ALERT_CONTACT_RATE_WINDOW_MINUTES:
    "Une chute soudaine du taux de contact : les minutes d'appels comparées aux 7 jours précédents de chaque campagne.",
  ALERT_CONTACT_RATE_DROP_PERCENT:
    "De combien le taux de contact doit baisser sur ces minutes, en pourcentage (40 : par ex. 30 % de contacts joints au lieu de 50 %).",
  ALERT_CONTACT_RATE_MIN_CALLS:
    "Le nombre minimum d'appels clôturés sur ces minutes pour que le taux de contact compte (les 7 jours précédents en demandent trois fois plus).",
  ALERT_CALLBACK_OVERDUE_MINUTES: "Un rappel toujours en attente autant de minutes après son échéance :",
  ALERT_MISSED_CALL_MINUTES: "Un appel entrant manqué que personne n'a rappelé autant de minutes après qu'il a sonné :",
  CRM_PROVIDER:
    "Le CRM d'où le poste d'appel tire ses prospects et où il écrit les résultats d'appel. Intégré : twenty. Un autre CRM se branche en ajoutant un adaptateur dans call_analyzer/adapters/crm/ (voir base.py).",
  CRM_BASE_URL:
    "Les appels sont associés aux contacts du CRM ayant le même numéro (Appels > un appel > onglet CRM).",
  CRM_API_KEY:
    "Dans Twenty : Settings > APIs & Webhooks > créer une clé API. Laissez vide pour désactiver l'onglet CRM.",
  CRM_VERIFY_SSL: "Mettez false si le CRM utilise un certificat auto-signé.",
  WHATSAPP_TOKEN:
    "API WhatsApp Cloud, pour les actions rapides du poste d'appel (grille tarifaire, comment déposer… : configurez-les ci-dessous une fois ces champs remplis). Depuis le tableau de bord d'application Meta > WhatsApp > API Setup. Utilisez le jeton d'accès permanent d'un utilisateur système (Business Settings > System users) avec whatsapp_business_messaging et whatsapp_business_management : le jeton temporaire affiché sur API Setup expire au bout d'un jour.",
  WHATSAPP_PHONE_NUMBER_ID:
    "L'« ID du numéro de téléphone » depuis lequel les messages sont envoyés (pas le numéro lui-même).",
  WHATSAPP_BUSINESS_ACCOUNT_ID:
    "L'« ID du compte WhatsApp Business », où se trouvent les modèles de messages approuvés : affiché sous le numéro sur la page WhatsApp > API Setup de l'application. Pas le « Business ID » du portefeuille (business.facebook.com > Business info), même si l'application retrouve le bon compte à partir de celui-ci si le jeton y a accès.",
  WHATSAPP_API_VERSION: "Version de l'API Graph.",
  TRANSCRIBE_PROVIDER:
    "local = Whisper gratuit sur ce PC (par défaut) ; elevenlabs / openai = API payantes",
  WHISPER_MODEL:
    "large-v3-turbo (rapide, tient sur un GPU de 4 Go) | large-v3 (le plus précis, demande plus de mémoire) | medium | small. Adaptés à la derja tunisienne : tunisian-large-v3 (derja + français, le plus précis) | arabic-dialectal-turbo (plus rapide) (téléchargés et convertis à la première utilisation ; nécessite requirements-convert.txt)",
  WHISPER_MODEL_DIR: "Où les modèles sont stockés. Vide = data/models dans ce projet.",
  WHISPER_DEVICE: "auto = GPU si disponible, sinon CPU | cuda | cpu",
  WHISPER_LANGUAGE:
    "Vide = détection automatique par appel. Mettez « ar » si la plupart des appels sont en derja, « fr » s'ils sont surtout en français.",
  WHISPER_PROMPT:
    "Phrase d'exemple dans le style de vos appels (derja en écriture arabe, mots français en écriture latine, noms de produits). Fortement recommandé : améliore nettement la transcription derja/français.",
  ANALYSIS_BACKEND:
    "claude = Claude uniquement. cursor = Cursor uniquement (nécessite CURSOR_API_KEY). auto = Claude d'abord, puis Cursor si la CLI Claude est absente ou la limite de session atteinte.",
  CLAUDE_BACKEND:
    "subscription = utilise la CLI Claude Code sur laquelle vous êtes connecté (offre Pro/Max, sans clé API) ; api = utilise ANTHROPIC_API_KEY (paiement au jeton). Utilisé quand ANALYSIS_BACKEND vaut claude ou auto.",
  CLAUDE_CODE_OAUTH_TOKEN:
    "Serveurs/Docker avec CLAUDE_BACKEND=subscription : lancez `claude setup-token` sur votre PC et collez le jeton ici.",
  CURSOR_MODEL: "Modèle pour l'analyse Cursor. composer-2.5 est la valeur par défaut actuelle.",
  FEEDBACK_LANGUAGE: "Langue dans laquelle les retours sont rédigés",
  VOICE_ANALYSIS:
    "true = écouter l'enregistrement lui-même (pas seulement la transcription) : un modèle d'émotions et des mesures de volume et de hauteur, que l'analyse transforme en note de ton de voix pour l'agent. Une étape du pipeline à part entière (téléchargement, voix, transcription, analyse). Le modèle d'émotions est converti une fois sur ce serveur (nécessite torch : pip install -r requirements-voice.txt ; variable de build Docker INSTALL_VOICE=true) puis fonctionne sans torch ; les agents distants téléchargent le modèle converti depuis ici. Sans modèle converti, seuls le volume et la hauteur sont mesurés.",
  VOICE_MODEL:
    "Le modèle d'émotions, l'un de la liste dans les paramètres (superb/wav2vec2-base-superb-er, Aniemore/wav2vec2-emotion-v1-crosslingual, Lajavaness/wav2vec2-lg-xlsr-fr-speech-emotion-recognition). Converti une fois à la première utilisation, ou avec Installer maintenant.",
  TRANSCRIBE_RUNS_ON:
    "Où s'exécute la transcription. host = ce serveur (nécessite Whisper ici). agent = uniquement sur les agents distants connectés : des PC qui exécutent `python -m call_analyzer agent run` (ajoutez-les sur la page Agents) ; les appels attendent dans une file jusqu'à ce qu'un agent soit en ligne. auto = sur un agent tant qu'il y en a un en ligne, sinon sur ce serveur.",
  VOICE_RUNS_ON:
    "Où s'exécute l'analyse vocale. Mêmes choix. Un agent télécharge le modèle d'émotions converti depuis ce serveur.",
  ANALYZE_RUNS_ON:
    "Où s'exécute l'analyse (Claude/Cursor). Mêmes choix que ci-dessus ; peut différer de la transcription, par ex. transcrire sur un PC avec GPU et analyser sur le serveur avec une clé API.",
  AGENT_DOWNLOAD_URL:
    "Où télécharger l'installateur de l'agent Windows, affiché lors de l'ajout d'un agent (facultatif). Ou copiez l'installateur dans le dossier downloads/ du répertoire de données et il est proposé depuis ce serveur.",
  AUTO_PROCESS:
    "true = tant que l'interface web tourne, récupérer régulièrement les nouveaux appels depuis GoVoice et les télécharger, transcrire et analyser automatiquement (sans rapports de coaching). Effet immédiat, sans redémarrage.",
  AUTO_PROCESS_MINUTES: "Minutes entre deux exécutions automatiques.",
  SKIP_NUMBERS:
    "Les appels vers ou depuis ces numéros ne sont jamais téléchargés, transcrits ni analysés, par ex. les téléphones de nos propres agents appelés via la VoIP. Séparez-les par des virgules. Avec ou sans +216 ; un poste (101) ignore tous ses appels.",
  SHARE_ON_LAN:
    "true = écouter sur le réseau local : les collègues peuvent se connecter et ouvrir les liens de partage sans se connecter. Nécessite un redémarrage de l'interface. Windows peut demander d'autoriser Python dans le pare-feu.",
  PUBLIC_URL:
    "Adresse utilisée pour accéder à l'application quand elle est hébergée, par ex. https://calls.example.com (utilisée dans les liens de partage).",
  COOKIE_SECURE:
    "true = n'envoyer le cookie de connexion qu'en HTTPS. À activer quand l'application est servie en HTTPS.",
  SESSION_DAYS: "Durée d'une connexion, en jours.",
  ADMIN_USERNAME:
    "Ce compte est créé au démarrage s'il n'existe pas encore. Ajoutez-en d'autres avec : python -m call_analyzer user add <nom>",
};
