<?php

namespace App\Command;

use App\Entity\Compte;
use App\Repository\CompteRepository;
use App\Service\Boites;
use Doctrine\ORM\EntityManagerInterface;
use Symfony\Component\Console\Attribute\AsCommand;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Output\OutputInterface;
use Symfony\Component\Console\Style\SymfonyStyle;
use Symfony\Component\DependencyInjection\Attribute\Autowire;

#[AsCommand(name: 'app:compte:creer', description: 'Crée le compte d\'un membre (ou renouvelle ses clés) et affiche son code de connexion')]
class CompteCreerCommand extends Command
{
    public function __construct(
        private CompteRepository $comptes,
        private EntityManagerInterface $em,
        #[Autowire('%env(RELAIS_URL)%')] private string $url,
    ) {
        parent::__construct();
    }

    protected function configure(): void
    {
        $this->addArgument('nom', InputArgument::REQUIRED, 'Prénom ou identifiant (minuscules, chiffres, . _ -)');
    }

    protected function execute(InputInterface $input, OutputInterface $output): int
    {
        $io = new SymfonyStyle($input, $output);
        $nom = strtolower(trim($input->getArgument('nom')));
        if (!preg_match('/^[a-z0-9][a-z0-9._-]{0,39}$/', $nom)) {
            $io->error('Nom invalide : minuscules, chiffres, . _ - (40 caractères max).');

            return Command::FAILURE;
        }
        $compte = $this->comptes->findOneBy(['nom' => $nom]);
        $existait = $compte !== null;
        $compte ??= new Compte($nom);
        [$envoi, $retrait] = $compte->renouvelerCles();
        $this->em->persist($compte);
        $this->em->flush();

        $io->success($existait ? "Clés RENOUVELÉES pour « $nom »." : "Compte créé pour « $nom ».");
        if ($existait) {
            $io->warning('Les anciennes clés ne fonctionnent plus : reconnectez le PC et refaites les raccourcis iPhone.');
        }
        $io->writeln('Code de connexion à coller dans l\'application (bouton « 📱 iPhone ») :');
        $io->newLine();
        $io->writeln('  '.Boites::codeConnexion($this->url, $nom, $envoi, $retrait));
        $io->newLine();
        $io->writeln('Transmettez-le par un canal sûr : il donne accès à la boîte de '.$nom.'.');

        return Command::SUCCESS;
    }
}
