import { fundingNodes, fundingEdges } from "../data/funding";
import type { FundingOverlayEntry } from "../data/funding-types";

export function initFundingGraph(_overlayEntries: FundingOverlayEntry[] = []): void {
  // Task 4 replaces this with the full map. Touch the data so the validator runs.
  console.info(`/funding: ${fundingNodes.length} nodes, ${fundingEdges.length} edges`);
}
