-- Můj přehled gained Kontejnery na objemný odpad (16. 11. 2026): a subscription that chose every
-- kind there was gets the new one too; one that left some out keeps its choice.
UPDATE push_subscriptions SET kinds = kinds || '{kontejnery}'
WHERE kinds @> '{podnety,deska,uzavirky,usneseni,cisteni}' AND NOT kinds @> '{kontejnery}';
