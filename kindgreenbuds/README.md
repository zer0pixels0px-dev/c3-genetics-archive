# Archive Kind Green Buds — bibliothèque de génétiques

Cette archive conserve séparément les informations extraites des fiches de la **Marijuana Strain Library de Kind Green Buds**. La source de départ est l’index alphabétique public : <https://kindgreenbuds.com/marijuana-strain-library/>. L’index capturé contenait **1 263 URL uniques** sous `/marijuana-strains/`.

## Couverture vérifiée

**1 261 fiches profil ont un contenu de page correspondant à l’URL demandée.** Deux autres entrées — Fruity Thai et Wappa — ont répondu HTTP 200 mais leur URL finale et leur URL canonique pointaient vers l’index général. Elles sont conservées comme tentatives non résolues, pas comme fiches de cultivar. Le répertoire contient aussi une capture de l’index lui-même; ce fichier n’est pas un cultivar. Les comptes sont détaillés dans `metadata/manifest.json` et `metadata/unresolved_profile_urls.json`.

## Provenance et vérification

Chaque fiche conserve le nom tel qu’affiché dans l’index, l’URL demandée, l’URL finale, l’URL canonique lorsqu’elle est présente, l’heure UTC de collecte, le statut HTTP, les métadonnées publiées sur la page, les champs et textes extraits, ainsi que des empreintes SHA-256. L’index source est conservé dans `raw_pages/index_source.html`, avec son empreinte dans `metadata/index_capture.json`.

Pour vérifier une affirmation, ouvrir le champ `source_url` et comparer `final_response_url`, `canonical_url`, `article_text` et les empreintes. Les empreintes détectent une différence entre captures; elles ne sont pas une signature numérique délivrée par Kind Green Buds et ne certifient pas à elles seules l’auteur ou l’exactitude des informations.

## Séparation des sources

Ces fiches sont une source autonome **Kind Green Buds**. Leur présence dans cette bibliothèque ne prouve pas que C3 Industries ou C3 Innovative Solutions ait cultivé, vendu ou fourni les génétiques correspondantes. Les données C3, SQDC, OCS/Ontario, Reddit et autres plateformes sont archivées ailleurs, dans des enregistrements avec leurs propres URL de provenance.

Les descriptions de variétés, lignées, teneurs, effets, terpènes et données de culture sont des déclarations de la page source; elles ne sont pas indépendamment validées. Des noms semblables peuvent désigner des lignées différentes.

## Fichiers

- `metadata/profile_inventory.json` : inventaire source des 1 263 URL de profils.
- `records/<slug>.json` : fiches individuelles; les deux redirections non résolues ont `extraction_status=redirected_to_index`.
- `records/all_records.jsonl` et `records/all_records.csv` : exports agrégés.
- `metadata/manifest.json` : comptes, couverture, méthode et statistiques.
- `metadata/unresolved_profile_urls.json` : deux URL renvoyant vers l’index.
- `logs/crawl.log` : journal Scrapling; `crawl_kindgreenbuds.py` : script réutilisable.

## Méthode

Collecte de pages publiques avec Scrapling 0.5. `robots.txt` a été respecté; aucune connexion, proxy, API WordPress, CAPTCHA ou restriction d’accès n’a été contournée. Débit du crawl : une requête en vol par domaine, délai minimal de 1,5 seconde et AutoThrottle. Les empreintes SHA-256 sont des contrôles locaux d’intégrité, pas des signatures d’éditeur.
