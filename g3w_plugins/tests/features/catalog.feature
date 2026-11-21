@backend
Feature: Plugin catalog

  Scenario: Only catalogued plugins can be managed
    Then a catalogued plugin is accepted
    And an unknown plugin is rejected

  Scenario: A failed installation preserves the current configuration
    Given the plugin manager has enabled panoramax
    When installing pdnd fails due to a dependency conflict
    Then the dependency conflict is reported
    And the previous plugin configuration is preserved
