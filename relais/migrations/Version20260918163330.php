<?php

declare(strict_types=1);

namespace DoctrineMigrations;

use Doctrine\DBAL\Schema\Schema;
use Doctrine\Migrations\AbstractMigration;

/**
 * Auto-generated Migration: Please modify to your needs!
 */
final class Version20260918163330 extends AbstractMigration
{
    public function getDescription(): string
    {
        return '';
    }

    public function up(Schema $schema): void
    {
        // this up() migration is auto-generated, please modify it to your needs
        $this->addSql('CREATE TABLE compte (id INT AUTO_INCREMENT NOT NULL, nom VARCHAR(40) NOT NULL, empreinte_envoi VARCHAR(64) NOT NULL, empreinte_retrait VARCHAR(64) NOT NULL, cree_le DATETIME NOT NULL, UNIQUE INDEX UNIQ_CFF652606C6E55B5 (nom), UNIQUE INDEX UNIQ_CFF652607708AF95 (empreinte_envoi), UNIQUE INDEX UNIQ_CFF65260F6CF1F03 (empreinte_retrait), PRIMARY KEY (id)) DEFAULT CHARACTER SET utf8mb4');
        $this->addSql('CREATE TABLE depot (id VARCHAR(40) NOT NULL, ext VARCHAR(8) NOT NULL, nom_original VARCHAR(120) NOT NULL, titre VARCHAR(120) NOT NULL, taille BIGINT NOT NULL, date_depot DATETIME NOT NULL, compte_id INT NOT NULL, INDEX IDX_47948BBCFD646330 (date_depot), INDEX IDX_47948BBCF2C56620 (compte_id), PRIMARY KEY (id)) DEFAULT CHARACTER SET utf8mb4');
        $this->addSql('ALTER TABLE depot ADD CONSTRAINT FK_47948BBCF2C56620 FOREIGN KEY (compte_id) REFERENCES compte (id) ON DELETE CASCADE');
    }

    public function down(Schema $schema): void
    {
        // this down() migration is auto-generated, please modify it to your needs
        $this->addSql('ALTER TABLE depot DROP FOREIGN KEY FK_47948BBCF2C56620');
        $this->addSql('DROP TABLE compte');
        $this->addSql('DROP TABLE depot');
    }
}
