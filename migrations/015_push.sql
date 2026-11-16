-- Můj přehled: browser notifications (Web Push) about the streets someone chose. Nothing about
-- the person: the push service's address of one browser (endpoint and its keys, needed to send),
-- the chosen streets and kinds. A subscription the push service no longer knows is deleted.
CREATE TABLE IF NOT EXISTS push_subscriptions (
  endpoint    text PRIMARY KEY,          -- the browser's address at its push service
  p256dh      text NOT NULL,             -- its keys: the message is encrypted for it
  auth        text NOT NULL,
  obvod       text NOT NULL,
  streets     text[] NOT NULL,           -- slugs of the streets
  kinds       text[] NOT NULL,           -- petka.ulice.feed.KINDS keys
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  sent_at     timestamptz                -- the last message
);

-- What each subscription was already sent (or was there when it subscribed): a feed event's key.
-- Kept as long as the feed reaches back, then deleted.
CREATE TABLE IF NOT EXISTS push_sent (
  endpoint  text NOT NULL REFERENCES push_subscriptions ON DELETE CASCADE ON UPDATE CASCADE,
  key       text NOT NULL,
  at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (endpoint, key)
);
