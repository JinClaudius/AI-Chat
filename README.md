# Décisions techniques du chatbot Ollama

Ce document ne présente pas une liste de fonctionnalités. Il explique les trois problèmes qui ont guidé la conception du chatbot, les décisions prises pour les résoudre et les limites qui restent volontairement acceptées.

## 1. Cohérence de l'historique pendant le streaming

### Symptôme observé

Le message utilisateur était ajouté à `historique_messages` avant l'appel à Ollama. Si le streaming échouait après quelques morceaux, l'historique conservait une question sans réponse, ou pouvait conserver une réponse partielle.

Un second problème venait de la séparation confuse entre le message temporaire et l'historique confirmé : une liste de messages utilisateur persistait d'un tour à l'autre, ce qui pouvait renvoyer une ancienne question lors de la requête suivante.

### Décision prise

Une interaction est traitée comme une paire indivisible :

```text
message utilisateur + réponse assistant complète
```

Le message utilisateur courant est construit séparément de `historique_messages`. Il est envoyé temporairement à Ollama avec l'historique confirmé, mais il n'est ajouté définitivement qu'après la fin normale de la boucle de streaming.

En cas d'erreur pendant le streaming :

```text
historique confirmé inchangé
message temporaire abandonné
réponse partielle non enregistrée
```

Les erreurs de réponse et les erreurs de résumé sont également séparées par deux blocs `try`, car elles ne doivent pas modifier le même état.

### Pourquoi ce choix

L'historique ne contient ainsi que des échanges utilisables par le modèle. Une réponse interrompue ne peut pas donner l'impression qu'une interaction est terminée alors qu'elle ne l'est pas.

### Limite restante

Le texte partiel a déjà été affiché dans le terminal avant l'erreur. Il n'est pas enregistré dans l'historique, mais l'utilisateur peut l'avoir vu. Le programme ne sait pas reprendre automatiquement une réponse interrompue.

## 2. Comptage en tokens et marge de contexte

### Symptôme observé

Une limite de 20 interactions, soit 40 messages, ne suffisait pas à contrôler la taille réelle du contexte : une interaction courte et une interaction très longue ne consomment pas le même espace.

Avec une fenêtre estimée à 8 000 tokens pour `llama3`, remplir le contexte jusqu'à la limite aurait aussi laissé trop peu de place à la réponse suivante.

### Décision prise

Le déclenchement du résumé est basé sur une estimation de tokens, pas sur le nombre de messages :

```text
caractères / 4 ≈ tokens de contenu
```

Le seuil choisi est 70 % de la fenêtre :

```text
8 000 × 0,70 = 5 600 tokens
```

La règle pratique devient donc environ 22 400 caractères de contenu, avec une marge d'environ 2 400 tokens pour la réponse à venir.

L'estimation ajoute également environ 4 tokens structurels par message pour les rôles et les délimiteurs. Ce coût est approximatif, mais il évite de considérer uniquement le texte brut.

Quand le seuil est atteint, le programme tente d'abord de résumer. Si le résumé échoue, il retire des paires anciennes `user + assistant` afin de ne pas rester bloqué.

### Pourquoi ce choix

L'estimation par caractères est simple, locale et suffisante pour piloter une marge de sécurité sans ajouter immédiatement un tokenizer spécifique au modèle.

Le seuil de 70 % privilégie la stabilité : il vaut mieux résumer un peu tôt que découvrir la saturation après avoir déjà commencé une génération.

### Limite restante

Quatre caractères par token est une moyenne. Le français, les noms propres, le code, les nombres et les caractères spéciaux peuvent produire une estimation différente. La taille exacte devrait être mesurée avec le tokenizer réel du modèle pour une garantie stricte.

Le coût structurel est lui aussi estimé, non mesuré exactement.

## 3. Résumé général et faits durables séparés

### Symptôme observé

Prendre les premiers caractères de la dernière réponse ne résumait pas la conversation. Cette troncature pouvait couper une phrase et ignorait les échanges précédents.

Même un bon résumé court perd inévitablement des détails : prénom, date, préférence ou décision exprimée en passant. À l'inverse, accumuler tout l'historique faisait grossir le contexte sans limite.

Une première version ajoutait également les faits nouveaux aux anciens sans jamais en retirer. Les faits, injectés dans un message système, pouvaient alors dépasser le budget sans que la réduction de l'historique conversationnel puisse les supprimer.

### Décision prise

Deux mémoires de nature différente sont conservées :

```text
memoire_chatbot.txt
    résumé du fil principal

faits_chatbot.json
    faits durables, préférences, dates et décisions
```

Le résumé est généré par un appel Ollama séparé. Le modèle reçoit l'ancien résumé, les échanges confirmés et les faits déjà connus. Il doit retourner une structure JSON contenant un résumé et une liste complète de faits fusionnés et dédupliqués.

Le résumé vise environ 100 caractères, mais peut être plus long si les informations principales l'exigent. Une limite de sécurité de 2 000 caractères empêche toutefois un résumé exceptionnellement long de remplir le contexte système.

Pour les faits durables, deux protections sont combinées :

- le modèle doit fusionner et dédupliquer la liste complète ;
- le programme impose au maximum 50 faits et 4 000 caractères, en supprimant les plus anciens au-delà de ces bornes.

Après une génération réussie, les deux fichiers sont sauvegardés et l'historique court est recréé avec le message système, le résumé et les faits. Si l'utilisateur quitte avant le seuil de tokens, la même génération de mémoire est tentée sur les échanges restants.

### Pourquoi ce choix

La troncature simple est peu coûteuse, mais elle ne distingue pas une information importante d'une phrase secondaire. Le résumé conserve le thème général, tandis que le fichier des faits protège les informations qui doivent survivre à plusieurs sessions.

La fusion par le modèle préserve mieux les faits qu'une suppression aveugle. Le plafond déterministe reste nécessaire pour garantir que la mémoire ne peut pas grossir indéfiniment si le modèle renvoie une liste trop longue.

### Limites restantes

Le modèle peut produire un JSON invalide, oublier un fait ou reformuler deux fois la même information. Dans ce cas, l'ancienne mémoire est conservée si la validation échoue, mais la qualité sémantique n'est pas garantie.

La déduplication compare les chaînes de caractères. Deux formulations différentes d'un même fait peuvent donc rester séparées.

Supprimer les faits les plus anciens protège la taille du contexte, mais peut supprimer une préférence encore pertinente. Une stratégie avec dates, importance ou expiration serait plus fidèle, mais ajouterait une logique métier et des décisions supplémentaires.

Les deux fichiers sont écrits séparément : une panne entre les écritures pourrait temporairement désynchroniser le résumé et les faits.

## Bilan

Les décisions privilégient la cohérence, une taille de contexte maîtrisée et une mémoire durable séparée. Elles ne prétendent pas supprimer toute perte d'information : elles rendent les compromis explicites et empêchent surtout les erreurs silencieuses de contaminer les sessions suivantes.

Les validations locales couvrent la syntaxe Python, l'estimation des tokens, le parsing JSON et les plafonds de faits. Un test complet avec un serveur Ollama réel reste nécessaire pour vérifier les réponses du modèle et la qualité des résumés.
