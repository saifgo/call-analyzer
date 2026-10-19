import type { leads as en } from "../en/leads";
import type { Translation } from "../types";

export const leads: Translation<typeof en> = {
  "leads.copyNumber": "Copier {number}",
  "leads.notCalledYet": "Pas encore appelé",
  "leads.lastCall": "dernier le {date}",
  "leads.allOwners": "Tous les responsables",
  "leads.description":
    "Les opportunités à l'étape Nouveau dans le CRM, les plus récentes d'abord, avec le numéro de leur interlocuteur.",
  "leads.loadFailed": "Impossible de charger les prospects",
  "leads.crmNotConnected": "Le CRM n'est pas connecté",
  "leads.crmNotConnectedHint": "Ajoutez votre clé API Twenty (CRM_API_KEY) dans les paramètres pour lister les prospects.",
  "leads.search": "Rechercher des prospects",
  "leads.searchPlaceholder": "Rechercher un nom, un numéro ou une ville",
  "leads.owner": "Responsable",
  "leads.countOf_one": "{shown} sur {count} nouveau prospect",
  "leads.countOf_other": "{shown} sur {count} nouveaux prospects",
  "leads.notCalledCount_one": "{count} pas encore appelé",
  "leads.notCalledCount_other": "{count} pas encore appelés",
  "leads.loading": "Chargement des prospects depuis le CRM…",
  "leads.lead": "Prospect",
  "leads.created": "Créé",
  "leads.ourCalls": "Nos appels",
  "leads.openInCrm": "Ouvrir dans le CRM",
  "leads.noContact": "Aucun interlocuteur",
  "leads.noNumber": "Aucun numéro",
  "leads.noMatch": "Aucun prospect ne correspond",
  "leads.noNew": "Aucun nouveau prospect",
  "leads.allMovedOn": "Toutes les opportunités du CRM ont dépassé l'étape Nouveau.",
  "leads.truncated_one": "Affichage du {count} nouveau prospect le plus récent ; le CRM en contient davantage.",
  "leads.truncated_other": "Affichage des {count} nouveaux prospects les plus récents ; le CRM en contient davantage.",
};
