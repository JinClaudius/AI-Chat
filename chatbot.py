import json
from pathlib import Path

import ollama


FICHIER_MEMOIRE = Path("memoire_chatbot.txt")
FICHIER_FAITS = Path("faits_chatbot.json")
FENETRE_MODELE = 8000
TAUX_DECLENCHEMENT = 0.70
SEUIL_RESUME = int(FENETRE_MODELE * TAUX_DECLENCHEMENT)
CARACTERES_PAR_TOKEN = 4
TOKENS_STRUCTURE_PAR_MESSAGE = 4
MAX_FAITS = 50
MAX_CARACTERES_FAITS = 4000
MAX_CARACTERES_RESUME = 2000


def estimer_tokens(messages):
    nombre_caracteres = sum(len(message["content"]) for message in messages)
    tokens_contenu = nombre_caracteres // CARACTERES_PAR_TOKEN
    tokens_structure = len(messages) * TOKENS_STRUCTURE_PAR_MESSAGE
    return tokens_contenu + tokens_structure


def charger_memoire():
    if FICHIER_MEMOIRE.exists():
        return FICHIER_MEMOIRE.read_text(encoding="utf-8").strip()
    return ""


def limiter_faits(faits):
    faits_uniques = []
    for fait in reversed(faits):
        if not isinstance(fait, str):
            continue

        fait = fait.strip()
        if fait and fait not in faits_uniques:
            faits_uniques.append(fait)

    faits_uniques.reverse()

    while len(faits_uniques) > MAX_FAITS or len(
        json.dumps(faits_uniques, ensure_ascii=False)
    ) > MAX_CARACTERES_FAITS:
        if not faits_uniques:
            break
        faits_uniques.pop(0)

    return faits_uniques


def charger_faits():
    if not FICHIER_FAITS.exists():
        return []

    try:
        donnees = json.loads(FICHIER_FAITS.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    return limiter_faits(donnees) if isinstance(donnees, list) else []


def sauvegarder_memoires(resume, faits):
    FICHIER_MEMOIRE.write_text(resume, encoding="utf-8")
    FICHIER_FAITS.write_text(
        json.dumps(limiter_faits(faits), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def creer_historique(resume, faits):
    faits = limiter_faits(faits)
    historique = [
        {
            "role": "system",
            "content": "Tu es un assistant virtuel utile, amical et concis.",
        }
    ]

    if resume:
        historique.append(
            {
                "role": "system",
                "content": f"Mémoire des conversations précédentes : {resume}",
            }
        )

    if faits:
        historique.append(
            {
                "role": "system",
                "content": (
                    "Faits durables connus : "
                    f"{json.dumps(faits, ensure_ascii=False)}"
                ),
            }
        )

    return historique


def extraire_json(texte):
    texte = texte.strip()
    if texte.startswith("```"):
        lignes = texte.splitlines()
        texte = "\n".join(lignes[1:-1]).strip()
    return json.loads(texte)


def generer_memoires(nom_modele, historique, ancien_resume, anciens_faits):
    contenu = "\n".join(
        f"{message['role']}: {message['content']}"
        for message in historique
        if message["role"] != "system"
    )

    instruction = (
        "Retourne uniquement un objet JSON valide avec exactement deux clés : "
        '"resume" et "faits". '
        "resume doit être une seule phrase concise qui conserve les informations "
        "principales. Vise environ 100 caractères, mais dépasse si nécessaire. "
        "faits doit être la liste complète fusionnée et dédupliquée des faits "
        "durables, préférences, dates ou décisions importantes. "
        f"Cette liste ne doit pas dépasser {MAX_FAITS} éléments ni "
        f"{MAX_CARACTERES_FAITS} caractères. "
        "Ne mets pas les détails temporaires dans faits.\n\n"
        f"Ancien résumé : {ancien_resume or 'Aucun'}\n"
        f"Anciens faits : {json.dumps(anciens_faits, ensure_ascii=False)}\n\n"
        f"Nouvelles interactions :\n{contenu}"
    )

    resultat = ollama.chat(
        model=nom_modele,
        messages=[
            {"role": "system", "content": "Tu es un outil de mémoire structuré."},
            {"role": "user", "content": instruction},
        ],
        stream=False,
    )

    donnees = extraire_json(resultat["message"]["content"])
    resume = donnees.get("resume", "")
    faits = donnees.get("faits", [])

    if not isinstance(resume, str) or not resume.strip():
        raise ValueError("Le résumé est vide ou invalide.")
    if len(resume.strip()) > MAX_CARACTERES_RESUME:
        raise ValueError("Le résumé dépasse la taille maximale autorisée.")
    if not isinstance(faits, list):
        raise ValueError("La liste des faits est invalide.")

    return resume.strip(), limiter_faits(faits)


def mettre_a_jour_memoires(nom_modele, historique, resume, faits):
    nouveau_resume, nouveaux_faits = generer_memoires(
        nom_modele,
        historique,
        resume,
        faits,
    )
    sauvegarder_memoires(nouveau_resume, nouveaux_faits)
    return nouveau_resume, nouveaux_faits


def reduire_historique(historique):
    messages_systeme = [
        message for message in historique if message["role"] == "system"
    ]
    messages_conversation = [
        message for message in historique if message["role"] != "system"
    ]

    while messages_conversation and estimer_tokens(
        messages_systeme + messages_conversation
    ) >= SEUIL_RESUME:
        messages_conversation = messages_conversation[2:]

    return messages_systeme + messages_conversation


def contient_conversation(historique):
    return any(message["role"] != "system" for message in historique)


def demarrer_chatbot():
    nom_modele = "llama3"
    memoire_resume = charger_memoire()
    faits_durables = charger_faits()
    historique_messages = creer_historique(memoire_resume, faits_durables)

    print("--- Chatbot Ollama Activé (Tapez 'exit' pour quitter) ---")

    while True:
        prompt_utilisateur = input("\nVous : ")

        if prompt_utilisateur.strip().lower() == "exit":
            if contient_conversation(historique_messages):
                try:
                    memoire_resume, faits_durables = mettre_a_jour_memoires(
                        nom_modele,
                        historique_messages,
                        memoire_resume,
                        faits_durables,
                    )
                except Exception as erreur:
                    print(f"\nRésumé non sauvegardé : {erreur}")

            print("Chatbot déconnecté. À bientôt !")
            break

        if not prompt_utilisateur.strip():
            continue

        message_utilisateur = {
            "role": "user",
            "content": prompt_utilisateur,
        }

        if estimer_tokens(historique_messages + [message_utilisateur]) >= SEUIL_RESUME:
            if contient_conversation(historique_messages):
                try:
                    memoire_resume, faits_durables = mettre_a_jour_memoires(
                        nom_modele,
                        historique_messages,
                        memoire_resume,
                        faits_durables,
                    )
                    historique_messages = creer_historique(
                        memoire_resume,
                        faits_durables,
                    )
                except Exception as erreur:
                    print(f"\nRésumé non sauvegardé : {erreur}")
                    historique_messages = reduire_historique(historique_messages)

        try:
            print("IA : ", end="", flush=True)
            flux_reponse = ollama.chat(
                model=nom_modele,
                messages=historique_messages + [message_utilisateur],
                stream=True,
            )

            reponse_complete = ""
            for morceau in flux_reponse:
                texte = morceau["message"]["content"]
                print(texte, end="", flush=True)
                reponse_complete += texte

            historique_messages.append(message_utilisateur)
            historique_messages.append(
                {"role": "assistant", "content": reponse_complete}
            )
            print()

        except Exception as erreur:
            print(f"\nErreur de réponse : {erreur}")
            continue

        if estimer_tokens(historique_messages) >= SEUIL_RESUME:
            try:
                memoire_resume, faits_durables = mettre_a_jour_memoires(
                    nom_modele,
                    historique_messages,
                    memoire_resume,
                    faits_durables,
                )
                historique_messages = creer_historique(
                    memoire_resume,
                    faits_durables,
                )
            except Exception as erreur:
                print(f"\nRésumé non sauvegardé : {erreur}")
                historique_messages = reduire_historique(historique_messages)


if __name__ == "__main__":
    demarrer_chatbot()
