<?php

namespace App\Command;

use App\Repository\CompteRepository;
use App\Service\Boites;
use Doctrine\ORM\EntityManagerInterface;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\Console\Style\SymfonyStyle;
use Symfony\Component\Filesystem\Filesystem;

#[AsCommand(name: 'app:compte:supprimer', description: 'Supprime un compte et sa boîte (fichiers en attente compris)')]
class CompteSupprimerCommand extends Command
{
    public function __construct(private CompteRepository $comptes, private EntityManagerInterface $em, private Boites $boites)
    {
        parent::__construct();
    }

    protected function configure(): void
    {
        $this->addArgument('nom', InputArgument::REQUIRED);
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $io = new SymfonyStyle($input, $output);
        $nom = strtolower(trim($input->getArgument('nom')));
        $compte = $this->comptes->findOneBy(['nom' => $nom]);
        if (!$compte) {
            $io->error("Pas de compte « $nom ».");

            return Command::FAILURE;
        }
        (new Filesystem())->remove($this->boites->dossier($compte));
        $this->em->remove($compte);        // les depots suivent (ON DELETE CASCADE)
        $this->em->flush();
        $io->success("Compte « $nom » et sa boîte supprimés.");

        return Command::SUCCESS;
    }
}
