// Server functions exposed to client/loaders for SimBench networks.
// Importing this file from a route is safe — the build strips the handler
// body from the client bundle.

import { createServerFn } from "@tanstack/react-start";
import { fetchNetworksFromService } from "./networks.server";

export const fetchSimbenchNetworks = createServerFn({ method: "GET" }).handler(
  async () => {
    return fetchNetworksFromService({
      serviceUrl: process.env.SIMBENCH_SERVICE_URL,
      serviceToken: process.env.SIMBENCH_SERVICE_TOKEN,
    });
  },
);
