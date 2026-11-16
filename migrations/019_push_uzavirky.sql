-- Můj přehled gained Uzavírky (16. 11. 2026): a subscription that chose every kind there was
-- gets the new one too; one that left some out keeps its choice.
UPDATE push_subscriptions SET kinds = kinds || '{uzavirky}'
WHERE kinds @> '{podnety,deska,usneseni,cisteni}' AND NOT kinds @> '{uzavirky}';
