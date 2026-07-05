"use client"

import { useState } from "react"
import ExecutionModeSelector from "@/components/procurement/ExecutionModeSelector"
import ProcurementForm from "@/components/procurement/ProcurementForm"
import type { ExecutionMode } from "@/lib/types"

/**
 * Client wrapper for /request/new.
 *
 * Holds the execution_mode state so the server page can remain a pure RSC
 * (auth check only). ExecutionModeSelector is passed into ProcurementForm as
 * a render slot; removing it requires changes only in this file.
 */
export default function NewRequestClient() {
  const [executionMode, setExecutionMode] = useState<ExecutionMode>("advisory")

  return (
    <ProcurementForm
      executionMode={executionMode}
      modeSelector={
        <ExecutionModeSelector
          value={executionMode}
          onChange={setExecutionMode}
          compact
        />
      }
    />
  )
}
