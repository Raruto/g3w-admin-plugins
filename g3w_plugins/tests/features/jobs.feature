@backend
Feature: Background plugin preparation

  Background:
    Given an isolated background job directory

  Scenario: The manager package takes precedence over the QGIS plugins namespace
    When starting a job cannot launch its process
    Then the launch error is reported
    And the manager package is first on the child Python path

  Scenario: Preparation survives its web worker and excludes concurrent changes
    Given a blocking preparation command
    When a web worker starts preparation
    Then the preparation is running in the migration phase
    And another preparation is rejected
    When the web worker exits
    Then the preparation is still running
    When the preparation command finishes
    Then preparation succeeds and the plugin is disabled

  Scenario: A failed preparation and an interrupted job are reported
    Given a preparation command that fails migration
    When a web worker starts the failing preparation
    Then the migration error is reported without saving state
    When a previously running job is found without a worker
    Then the job is reported as interrupted

  Scenario: Automatic reload runs after the original worker has exited
    Given Linux pidfd reload support and a blocking preparation command
    When a master starts a worker that exits during preparation
    Then the preparation is running in the migration phase
    When the preparation command finishes
    Then the master is reloaded with the prepared configuration

  Scenario: A reload failure keeps the prepared configuration
    When preparation succeeds but the master is unavailable
    Then the reload failure and prepared target are recorded

  Scenario: An update job forwards the requested version
    When an update to version 1.2 is prepared for an unmanaged enabled plugin
    Then the update uses that version and succeeds

  Scenario: A failed reload can be retried
    Given a failed reload for panoramax
    When reload is retried
    Then the requested configuration is recorded without the previous error

  Scenario: A killed preparation retains its locks while its command runs
    Given a blocking preparation command that records its parent
    When a web worker starts preparation
    And the preparation process is killed
    Then its locks prevent another change
    When the preparation command finishes
    Then the interruption is reported without saving state
