@backend
Feature: Plugin administration status and controls

  Background:
    Given an isolated plugin administration request

  Scenario: Only active superusers see the plugin menu
    When the sidebar is filtered for users with different permissions
    Then only active superusers see the plugin entry

  Scenario: Existing sidebar hooks remain installed
    When the plugin registers its sidebar hook twice
    Then the existing two-argument and three-argument hooks are preserved

  Scenario: Successful startup is logged
    When the plugin initializes its application
    Then an informational startup event is logged

  Scenario: Failed startup does not log success
    When plugin application initialization fails
    Then no startup success event is logged

  Scenario: Status confirms only the active web worker configuration
    When status is requested for matching and outdated web configurations
    Then only the matching web configuration is confirmed

  Scenario: Status reports consumer confirmation
    When status is requested with the consumer disabled, pending and ready
    Then consumer flags and plugin status reflect each condition

  Scenario: Confirmed success starts hidden with locale-independent identity
    When a confirmed success is rendered in Italian
    Then the hidden notification retains the unlocalized timestamp

  Scenario: Status URLs follow the renamed application
    When the frontend is enabled or disabled
    Then the alternate status URL points to the other application path

  Scenario: Installed versions are shown when metadata exists
    When one plugin has package metadata and another does not
    Then their versions reflect the available metadata

  Scenario: Actions reflect desired state while preparation is running
    When plugin rows are rendered for running and desired states
    Then each row shows exactly one disabled action and the correct status

  Scenario: Row status reports preparation and reload progress
    When a plugin is updated through each preparation and reload phase
    Then the row describes its current phase, failure or reload state

  Scenario: An asynchronous rejection is reported
    When an asynchronous activation is rejected as already running
    Then the response contains the rejection

  Scenario: Version checks compare releases and report failures
    When a version check completes, is pending or fails
    Then access, versions, errors and invalid plugin names are handled correctly

  Scenario: The selected update version reaches the background job
    When a superuser requests version 1.10 of panoramax
    Then the update job receives that version

  Scenario: Bundled modules and their dependencies appear in status
    When editing and qplotly are configured with qes installed
    Then bundled modules, warnings and sorted display names are reported

  Scenario: Bundled modules cannot be updated from PyPI
    When a superuser requests an editing update or version check
    Then both requests are rejected without starting work

  Scenario: Editing cannot be disabled from the web while qes is installed
    When a superuser disables editing with qes installed
    Then the dependency error is returned without starting a process

  Scenario: Editing cannot be disabled from the CLI while qes is installed
    When the CLI disables editing with qes installed
    Then the CLI reports the dependency error

  Scenario: Bundled rows show dependencies instead of PyPI controls
    When the editing row is rendered with qes installed
    Then it shows the bundled source and warning without PyPI controls
