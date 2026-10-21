# CineDub worker

The worker is a separate process even though it imports the shared API package. It polls durable jobs from the database and executes media or provider operations outside the web request cycle.
