import type { pages as en } from "../en/pages";
import type { Translation } from "../types";

export const pages: Translation<typeof en> = {
  "login.unreachable": "Impossible de joindre le serveur",
  "login.signIn": "Se connecter",
  "login.description": "Utilisez le compte que votre responsable a créé pour vous.",
  "login.username": "Nom d'utilisateur",
  "login.password": "Mot de passe",
  "login.hidePassword": "Masquer le mot de passe",
  "login.showPassword": "Afficher le mot de passe",

  "business.saved": "Contexte métier enregistré",
  "business.description":
    "Ce que vous vendez, votre appel idéal, les objections courantes et qui est sur quel poste. L'analyse juge chaque appel par rapport à ce contexte.",
  "business.reanalyzeHint":
    "Après une modification, réanalysez les appels (Pipeline → Analyser avec « Refaire ») pour mettre à jour les retours existants.",
  "business.textareaLabel": "Contexte métier (Markdown)",

  "feedback.allAuthors": "Tous les auteurs",
  "feedback.descriptionAdmin":
    "Tout ce que l'équipe a écrit sur les appels. Ouvrez une ligne pour voir l'appel, et ajoutez ou modifiez un retour depuis celui-ci.",
  "feedback.descriptionAgent": "Ce que les relecteurs ont écrit sur vos appels.",
  "feedback.search": "Rechercher dans les retours",
  "feedback.searchPlaceholder": "Rechercher un retour, un numéro ou un ID d'appel",
  "feedback.author": "Auteur",
  "feedback.notes_one": "{count} note",
  "feedback.notes_other": "{count} notes",
  "feedback.loading": "Chargement des retours…",
  "feedback.added": "Ajouté",
  "feedback.feedback": "Retour",
  "feedback.score": "Note",
  "feedback.call": "Appel",
  "feedback.edited": "modifié {time}",
  "feedback.humanScore": "Humain {score}/10",
  "feedback.ai": "IA",
  "feedback.noneFound": "Aucun retour trouvé",
  "feedback.emptyAdmin": "Ouvrez un appel et utilisez son onglet Retours humains pour écrire la première note.",
  "feedback.emptyAgent": "Personne n'a encore écrit de retour sur vos appels.",
  "feedback.showingLatest": "Affichage des {shown} plus récents sur {total}. Recherchez pour affiner.",

  "reports.wholeTeam": "Toute l'équipe",
  "reports.shareDescription":
    "Un lien privé vers ce rapport de coaching. Toute personne disposant du lien peut le lire sans se connecter.",
  "reports.noLink": "Aucun lien n'existe encore pour ce rapport.",
  "reports.generate": "Générer les rapports",
  "reports.descriptionAdmin": "Rapports de coaching pour toute l'équipe et pour chaque agent.",
  "reports.descriptionAgent": "Vos rapports de coaching.",
  "reports.none": "Aucun rapport pour l'instant",
  "reports.emptyAdmin": "Analysez quelques appels, puis générez des rapports de coaching à partir de ceux-ci.",
  "reports.emptyAgent": "Vos rapports de coaching apparaîtront ici dès que votre responsable les aura générés.",

  "share.title": "Lien de partage",
  "share.revoked": "Lien de partage révoqué",
  "share.copy": "Copier le lien",
  "share.localOnly": "Fonctionne uniquement sur cet ordinateur",
  "share.localOnlyHint":
    "Pour partager avec d'autres, définissez PUBLIC_URL (hébergé) ou SHARE_ON_LAN=true (réseau local) dans les paramètres et redémarrez l'application. Pour l'envoyer à n'importe qui, téléchargez plutôt le PDF.",
  "share.revoke": "Révoquer le lien",
  "share.open": "Ouvrir",
  "share.create": "Créer un lien",
  "share.pdfStarting": "Le téléchargement démarre dans quelques secondes.",
  "share.creatingPdf": "Création du PDF…",
  "share.downloadPdf": "Télécharger le PDF",
};
